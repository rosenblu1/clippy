#!/Library/Frameworks/Python.framework/Versions/3.11/bin/python3
# BUILD:
# $ ./build.sh
#  !! current directory should have an assets/ folder with:
#  !! AppIcon.icns, cup_10_pt.svg, installer_background.png
# login item:
#   https://github.com/RhetTbull/textinator/blob/main/src/loginitems.py

# TODO: if we auto-update (or manually re-download), keep ClippyCache somehow

from __future__ import annotations

__version__ = "0.1.1"
__author__ = "Eddie Rosenblum"
__contact__ = "yaplore@gmail.com"
__license__ = "GPLv3"

import glob
import logging
import math
import multiprocessing
import os
import signal
import subprocess
import sys
import threading
import time
from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from functools import partial
from typing import Any, Callable

import requests
import richxerox
import rumps
from AppKit import NSBundle, NSPasteboard
from PIL import Image, ImageGrab

# file constants
APP_NAME = "Clippy"
WORKING_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = f"{WORKING_DIR}/{APP_NAME}Cache"
APP_MENUBAR_ICON = f"{WORKING_DIR}/assets/cup_10_pt.svg"
APP_FINDER_ICON = f"{WORKING_DIR}/assets/AppIcon.icns"
SERIALIZED_FP = f"{CACHE_DIR}/cached_items.pickle"
EXEMPT_CACHE_FILETYPES = (".log", ".pickle")

# releases
DIST_LATEST_LINK = "https://github.com/rosenblu1/clippy/releases/latest"
DIST_DOWNLOAD_ROUTE = "download"
DIST_INSTALLER_NAME = f"{APP_NAME}-Installer.dmg"

# logging
LOG_TO_STDOUT = sys.argv is not None and "--stdout" in sys.argv
LOG_FILE = f"{WORKING_DIR}/{APP_NAME}Log.log"
CODEX_OPT = ("ascii", "ignore")

# clipboard logic
DEFAULT_CLIP_HISTORY = 25
TIME_STEP = 1.0
TARGET_IMAGE_AREA = 20_000
PREFERRED_TITLE_ORDER_URI_S = ["public.file-url", "text"]

# thread safety
PROGRAM_CLIP_SET_EVENT = threading.Event()
PROGRAM_CLIP_OPERATION = threading.Lock()
LOCK_TIMEOUT = 1.0

# UnreliableFunctionCall
RISKY_FUNC_CALL_TRIES = 2
RISKY_FUNC_CALL_TIME_LIMIT = 1.0
RISKY_FUNC_REST_TIME = 0.1

# Objective C values for GUI states
GUI_ITEM_STATE_PINNED = -1
GUI_ITEM_STATE_OFF = 0

# handled signals that trigger quit
QUIT_SIGNALS = [
    signal.SIGTERM,
    signal.SIGHUP,
    signal.SIGPIPE,
    signal.SIGTSTP,
    signal.SIGINT,
    signal.SIGQUIT,
    signal.SIGABRT,
]


def config_script_for_background_use():
    """
    Sets background ObjC data so we don't get an icon in
    the dock while running, as well as only alerting us when PIL
    encounters a critical error.
    """
    app_info = NSBundle.mainBundle().infoDictionary()
    app_info["LSUIElement"] = 1
    logging.getLogger("PIL").setLevel(logging.CRITICAL)


def config_script_directories():
    """
    Creates cache directory if nonexistant.
    """
    if os.path.isdir(CACHE_DIR):
        return
    os.makedirs(CACHE_DIR)


def get_newest_app_version() -> str | None:
    _log("attempting to get newest app version")
    try:
        redirect = requests.get(
            DIST_LATEST_LINK, timeout=RISKY_FUNC_CALL_TIME_LIMIT
        ).url
    except BaseException as e:
        _log(f"exception getting newest app version: {e}")
        return
    if redirect is None:
        return
    return str(redirect).split("/")[-1][1:]


def _log(printable: str) -> None:
    """Log data to LOG_FILE in cache directory or to sys.stdout."""
    if LOG_TO_STDOUT:
        print(_fmt_log_str(printable))
        return
    if not os.path.isfile(LOG_FILE):
        config_script_directories()
    with open(LOG_FILE, "a") as f:
        try:
            f.write(f"{_fmt_log_str(printable)}\n")
        except UnicodeEncodeError:
            pass


def _fmt_log_str(printable: str) -> str:
    """Formats timestamped, ASCII-safe string for _log"""
    return f"{datetime.now()} {str(printable).encode(*CODEX_OPT).decode(*CODEX_OPT)}"


def clip_setter(func):
    """
    Decorator for methods that set the system clipboard. Gets program lock
    and sets PROGRAM_CLIP_SET_EVENT for heartbeat function to handle.
    """

    def inner(*args, **kwargs):
        if not PROGRAM_CLIP_OPERATION.acquire(blocking=True, timeout=LOCK_TIMEOUT):
            _log(f"{func.__name__} failed to acquire lock, clip set not done")
            return
        func_ret = func(*args, **kwargs)
        PROGRAM_CLIP_SET_EVENT.set()
        PROGRAM_CLIP_OPERATION.release()
        return func_ret

    return inner


class UnreliableFunctionCall:
    """
    Used to make function calls that unexpectedly freeze/hang safe to call
    by running them in a separate process, killing if they take too long, and re-trying
    num_tries amount of times with a short pause in-between. Uses a multiprocessing.Queue
    to store the return value of the risky function.
    """

    def __init__(
        self,
        unsafe_func: Callable,
        num_tries: int = RISKY_FUNC_CALL_TRIES,
        time_per_try: float = RISKY_FUNC_CALL_TIME_LIMIT,
        rest_bw_tries: float = RISKY_FUNC_REST_TIME,
    ):
        self.f = unsafe_func
        self.num_tries = num_tries
        self.time_per_try = time_per_try
        self.rest_bw_tries = rest_bw_tries
        self._out_obj = multiprocessing.Queue(maxsize=1)

    def _threadable(self) -> None:
        """Target for spawned process"""
        ret_val = self.f()
        self._out_obj.put(ret_val)

    def _spawn_one_proc(self) -> multiprocessing.Process:
        """Create, start, and return process with risky function running"""
        proc = multiprocessing.Process(target=self._threadable, daemon=False)
        proc.start()
        return proc

    def get_safe_callable(self) -> Callable:
        """
        Returns a safe version of the risky function that will ensure
        it does not hang indefinitely when called.
        """

        def inner_func() -> Any | None:
            return_value = None
            for i in range(self.num_tries):
                _log(f"try {i+1}/{self.num_tries} for {self.f}...")
                proc = self._spawn_one_proc()
                start = time.time()
                proc.join(self.time_per_try)
                try:
                    return_value = self._out_obj.get_nowait()
                    _log(f"finished: took {time.time() - start:.4f} seconds")
                    proc.kill()
                    break
                except:
                    _log(f"timed out, killing...")
                    proc.kill()
                    time.sleep(self.rest_bw_tries)
            return return_value

        return inner_func


@dataclass
class ClipItem(ABC):
    """
    Abstract base dataclass for internal representation of items grabbed from clipboard.
    These items mirror the rumps.MenuItem objects that are pushed to the GUI.
    ClipItem.title is the key in app.menu to find its rumps.MenuItem.

    Currently instantiable subclasses are TextClip and ImageClip.

    We can't use inheritance or composition with rumps.MenuItem because PyObjC can't
    be serialized like we need for storing pinned items between sessions.
    """

    title: str
    is_pinned: bool = False
    raw_data: dict[str, str] | None = None
    persistent_id: Any = None
    icon: str | None = None
    dimensions: tuple[int, int] | None = None

    @abstractmethod
    def recopy(self, sender: rumps.MenuItem = None):
        """Copy full item data back to the clipboard"""
        ...

    @staticmethod
    @abstractmethod
    def grab_clipboard(data: Any) -> Any:
        """Get data currently copied from the system clipboard"""
        ...

    @abstractmethod
    def remove_persistent_data(self):
        """Clean up any data (e.g. files) that the item used"""
        ...


class TextClip(ClipItem):
    def recopy(self, sender: rumps.MenuItem = None):
        richxerox.copy(**self.raw_data, clear_first=True)
        _log(f"re-copied ~{self.title}~")

    def grab_clipboard() -> dict[str, str] | None:
        pasteall_made_safe = UnreliableFunctionCall(
            richxerox.pasteall
        ).get_safe_callable()
        data = pasteall_made_safe()
        _log(f"text clipboard grabbed with keys {[k for k in data]}")
        if data is not None and len(data):
            return {key: data[key] for key in data if data[key]}
        return None

    @staticmethod
    def get_displayable_title(data: dict[str, str]) -> str | None:
        """
        Pre-process the raw data recieved from the system clipboard
        and determine what the key/title should be in the menubar
        """
        for uri in PREFERRED_TITLE_ORDER_URI_S:
            if title := data.get(uri):
                return title
        return None

    def remove_persistent_data(self):
        pass

    def __str__(self) -> str:
        t = f"{self.title[:2]}...{self.title[-2:]}"
        r = self.raw_data.keys()
        return f"{__class__.__name__}(title={t}, raw={r}, pinned={self.is_pinned})"


class ImageClip(ClipItem):
    def recopy(self, sender: rumps.MenuItem = None):
        with open(f"{CACHE_DIR}/dump.dump", "w") as errdump_fd:
            subprocess.run(
                [
                    "osascript",
                    "-e",
                    f'set the clipboard to (read (POSIX file "{self.icon}") as JPEG picture)',
                ],
                stderr=errdump_fd,
            )
        _log(f"re-copied {self}")

    @staticmethod
    def grab_clipboard() -> Image.Image | None:
        img = ImageGrab.grabclipboard()
        _log(f"img clipboard grabbed: {img}")
        return img

    @staticmethod
    def save_persistent_data(data: Image.Image, persistent_id: str):
        """Save full image data to temp cache"""
        data.save(persistent_id)

    @staticmethod
    def get_scaled_size(data: Image.Image) -> tuple[int, int]:
        """
        Return image dimensions that should be shown in the GUI.
        Width and height scaled to have the same target number of pixels.
        """
        scale = (TARGET_IMAGE_AREA / (data.width * data.height)) ** 0.5
        return tuple(int(scale * dim) for dim in data.size)

    def remove_persistent_data(self):
        os.remove(self.icon)

    def __str__(self) -> str:
        i = self.icon
        d = self.dimensions
        return f"{__class__.__name__}(icon={i}, dims={d}, pinned={self.is_pinned})"


class InvisibleStringCounter:
    """
    Used as an iterator to dispatch strings representing ID's
    counting up from 1. ID strings are composed of control characters
    whose ASCII code corresponds to digits in the ID number.

    For example, an ID of 35 would correspond to the string chr(3)+chr(5).

    This iterator provides keys/titles for the GUI for items where we want
    to only show the icon (e.g. ImageClip items), but the menubar requires
    a text title.
    """

    def __iter__(self):
        self._counter = 0
        return self

    def __next__(self) -> str:
        stringified = self.int_to_invisible_str(self._counter)
        self._counter += 1
        return stringified

    def cur_int_count(self) -> int:
        """Current integer ID in the iterator"""
        return self._counter

    @staticmethod
    def int_to_invisible_str(count: int) -> str:
        """
        Convert digits of integer to string of control characters
        whose ASCII code are those digits.

        e.g. 410 -> '\x04\x01\x00'
        """
        if not count:
            return chr(0)
        digits = [
            (count // 10**power) % 10
            for power in range(int(math.log10(count)), -1, -1)
        ]
        return "".join([chr(d) for d in digits])


class ClipDataManager:
    """
    Intermediate step between the system clipboard and the program (i.e. ClippyApp)
    ClipItem storage; contains logic for polling system clipboard for updates
    and returning new ClipItem objects.
    """

    def __init__(self, id_dispatch: InvisibleStringCounter):
        # id dispatcher for items that don't have a title (images)
        self.id_dispatch = id_dispatch
        # hook into AppKit to see if we need to run a full check
        self.change_tracker_obj = NSPasteboard.generalPasteboard()
        self.change_count = self.change_tracker_obj.changeCount()
        # buffers for looping
        self.prev_txt_clip, self.cur_txt_clip = None, None
        self.prev_img_clip, self.cur_img_clip = None, None

    @staticmethod
    @clip_setter
    def clear_system_clipboard():
        """Clears system clipboard"""
        richxerox.clear()

    def update_buffers(self):
        """Set internal buffers to current value of system clipboard"""
        self.prev_txt_clip, self.cur_txt_clip = [TextClip.grab_clipboard()] * 2
        self.prev_img_clip, self.cur_img_clip = [ImageClip.grab_clipboard()] * 2
        _log("clip manager buffers updated")

    def has_change_count_mismatch(self) -> bool:
        """
        Determine if system clipboard reported an operation occured.
        Does not necessarily mean there is a new ClipItem to create -
        for example, clearing the clipboard will be reported as a change.
        """
        new_count = self.change_tracker_obj.changeCount()
        if self.change_count == new_count:
            return False
        _log(f"changeCount: app={self.change_count}, system={new_count}")
        return True

    def update_change_count(self):
        """Set internal change_count to system's changeCount"""
        self.change_count = self.change_tracker_obj.changeCount()

    def get_new_item(self) -> ClipItem | None:
        """Try to return a ClipItem subclass from the system clipboard"""
        # text
        self.cur_txt_clip = TextClip.grab_clipboard()
        if (
            self.prev_txt_clip != self.cur_txt_clip
            and self.cur_txt_clip is not None
            and (txt_title := TextClip.get_displayable_title(self.cur_txt_clip))
        ):
            self.prev_txt_clip = self.cur_txt_clip
            return TextClip(
                title=txt_title,
                raw_data=self.cur_txt_clip,
            )

        # images
        self.cur_img_clip = ImageClip.grab_clipboard()
        if self.prev_img_clip != self.cur_img_clip and self.cur_img_clip is not None:
            img_id = next(self.id_dispatch)
            img_path = f"{CACHE_DIR}/{self.id_dispatch.cur_int_count()}.jpg"
            ImageClip.save_persistent_data(self.cur_img_clip, img_path)
            img_dims = ImageClip.get_scaled_size(self.cur_img_clip)
            self.prev_img_clip = self.cur_img_clip
            return ImageClip(
                title=img_id, persistent_id=img_path, icon=img_path, dimensions=img_dims
            )

        _log("no new item found...")
        return None


class ClippyApp:
    """Main class that represents the current App state, composed with the rumps.App."""

    def __init__(
        self,
        name: str,
        icon: str,
        clip_manager: ClipDataManager,
        history_len: int,
    ):
        """
        ClippyApp's rumps.App GUI is stored in ClippyApp.gui,
        while the deque of ClipItems is in ClippyApp.items.

        Initializing ClippyApp also performs setup like registering
        signal handlers, setting up main menu, unserializing, etc.
        """
        self.gui = rumps.App(name=name, icon=icon, quit_button=None)

        # reserved keys for separators in the gui (can't copy these)
        self._gui_placement_key = "\x06pins_above_nonpins_below_separator\x06"
        self._bottom_bar_separator = "\x06bottom_bar_separator\x06"

        self.history_len = history_len
        self.items: deque[ClipItem] = deque()

        # manager for getting, preprocessing, and returning new items
        self.clip_manager = clip_manager

        # perform initialization methods
        self.register_signals(self.quit, QUIT_SIGNALS)
        self.setup_main_menu()
        self.try_unserialize_data()
        self.serialize_data(only_pinned=True)  # we might have non-pins from re-starting
        self.clip_manager.clear_system_clipboard()
        self.cleanup_unreferenced_persistent_data()

    @staticmethod
    def register_signals(on_program_end_fn, signals: list[signal.Signals]):
        """Registers callback for signals recieved by program."""
        for sig_type in signals:
            signal.signal(sig_type, partial(on_program_end_fn, sig_type=sig_type))

    def _add_bar_separator(self, this_separator_title: str):
        """Adds horizontal menu separator to GUI with key/title provided."""
        self.gui.menu[this_separator_title] = rumps.separator

    def display_about_app(self, sender: rumps.MenuItem):
        newest_version = get_newest_app_version()
        if newest_version is None:
            version_comment = ""
        elif newest_version == __version__:
            version_comment = f"You are using the most current release."
        else:
            version_comment = f"The most current release is v{newest_version}."
        _log(f"displaying about info with {version_comment=}")
        rumps.alert(
            title=f"{APP_NAME} v{__version__}",
            icon_path=APP_FINDER_ICON,
            message=f"""\
                        {version_comment}

                        Created by: {__author__}
                        Contact: {__contact__}

                        License: {__license__}
                        Newest version at:
                        {DIST_LATEST_LINK}/{DIST_DOWNLOAD_ROUTE}/{DIST_INSTALLER_NAME}
                        """,
        )

    def setup_main_menu(self):
        """
        Structure of the GUI from top to bottom:

        <pinned items>      (most recent pins on bottom)
        ------------------- (_gui_placement_key, all items grow outwards from here)
        <non-pinned items>  (most recent non-pins on top)
        ------------------- (_bottom_bar_separator)
        Clear All           --> [Keep pinned items, Remove everything]
        About
        Quit Clippy
        """
        self._add_bar_separator(self._gui_placement_key)
        self._add_bar_separator(self._bottom_bar_separator)

        # clear items and submenu
        clear_button_anchor = rumps.MenuItem(title="Clear All")
        clear_button_anchor.update(
            rumps.MenuItem(
                title="Keep pinned items",
                callback=partial(self.clear_all_items, respect_pins=True),
                key="w",
            )
        )
        clear_button_anchor.update(
            rumps.MenuItem(
                title="Remove everything",
                callback=partial(self.clear_all_items, respect_pins=False),
                key="\b",
            )
        )
        self.gui.menu.update(clear_button_anchor)

        # about button
        self.gui.menu.update(
            rumps.MenuItem(
                title="About",
                callback=self.display_about_app,
            )
        )

        # quit button
        self.gui.menu.update(
            rumps.MenuItem(title=f"Quit {self.gui.name}", callback=self.quit, key="q")
        )

    def add_clip_item_to_top(self, item: ClipItem):
        """
        Adds a clip item to the internal ClipItem deque and GUI.
        Tries to clear the item from both places before adding
        in case of re-copy.

        ClipItem is added directly before (i.e., above) ClippyApp._gui_placement_key
        if pinned, and directly after (i.e., below) if not pinned.
        """
        _log(f"adding item: {item}")
        # sanity check
        if item is None:
            _log("add_clip_item passed None ClipItem. not adding...")
            return
        if item.title in (self._gui_placement_key, self._bottom_bar_separator):
            _log(f"copied reserved key '{item.title}'. not adding...")
            return
        # make sure re-added items are on top
        self.try_clear_one_item(item=item, keep_persistent_data=True, no_log=True)
        # add to ClippyApp's list
        self.items.appendleft(item)
        # ensure menu is the correct size
        self.correct_items_length()
        # item to add to main gui menu
        item_anchor = self._create_item_copy_button(item)
        if item.is_pinned:
            item_anchor.state = GUI_ITEM_STATE_PINNED
        # add submenu of special buttons to item anchor
        item_anchor.update(
            (self._create_item_pin_button(item), self._create_item_remove_button(item))
        )
        # add item anchor to main gui menu
        # N.B. items grow outwards from both top and bottom of the placement key
        if item.is_pinned:
            self.gui.menu.insert_before(self._gui_placement_key, item_anchor)
        else:
            self.gui.menu.insert_after(self._gui_placement_key, item_anchor)

    def correct_items_length(self):
        """
        Ensure internal ClipItem deque and GUI only have history_len
        number of pinned and non-pinned items, combined.
        """
        len_diff = len(self.items) - self.history_len
        if not len_diff:
            return
        for loop_item in reversed(list(self.items)):
            len_diff -= 1
            if len_diff < 0:
                break
            if loop_item.is_pinned:
                continue
            self.try_clear_one_item(item=loop_item)

    def _create_item_copy_button(self, item: ClipItem) -> rumps.MenuItem:
        """
        Returns rumps.MenuItem for ClipItem with a callback of re-copying
        item data to system clipboard and re-adding to ClippyApp so most recently
        re-copied items are on top.
        """

        @clip_setter
        def recopy_and_remove(sender: rumps.MenuItem):
            item.recopy()
            if not item.is_pinned:
                self.add_clip_item_to_top(item)

        return rumps.MenuItem(
            title=item.title,
            callback=recopy_and_remove,
            icon=item.icon,
            dimensions=item.dimensions,
        )

    def _create_item_pin_button(self, item: ClipItem) -> rumps.MenuItem:
        """Returns rumps.MenuItem with callback of toggling item's pin state"""
        pin_button = rumps.MenuItem(
            title="📌 Pin", callback=partial(self.toggle_item_pin, item=item)
        )
        pin_button.state = int(item.is_pinned)
        return pin_button

    def _create_item_remove_button(self, item: ClipItem) -> rumps.MenuItem:
        """Returns rumps.MenuItem with callback of clearing item"""
        return rumps.MenuItem(
            title="🗑 Remove",
            callback=partial(self.try_clear_one_item, item=item),
        )

    def toggle_item_pin(self, sender: rumps.MenuItem = None, *, item: ClipItem):
        """
        Sets pin on ClipItem object, marks item's main copy button as pinned
        in the GUI with a "-", and marks the item's pin submenu button in the
        GUI with a "√". Then re-adds item so it appearss at the top, as well as
        re-serializes item cache so pins are saved in event of unexpected quit.
        """
        _log(f"toggling item pin for {item}...")
        # set pin (checkmark) on Pin submenu item
        sender.state = not sender.state
        # set pin on ClipItem
        item.is_pinned = not item.is_pinned
        # set pin (horizontal line) on main menu item
        item_gui_pointer: rumps.MenuItem = self.gui.menu[item.title]
        if item_gui_pointer.state == GUI_ITEM_STATE_PINNED:
            item_gui_pointer.state = GUI_ITEM_STATE_OFF
        else:
            item_gui_pointer.state = GUI_ITEM_STATE_PINNED
        # bring to top
        self.add_clip_item_to_top(item)
        # update cache
        self.serialize_data()

    def cleanup_unreferenced_persistent_data(self):
        """
        Ensures data that's not part of a ClipItem the app knows
        about is cleaned up, i.e. un-pinned images not properly removed.
        """
        persistent_ids = [item.persistent_id for item in self.items]
        for data in glob.iglob(f"{CACHE_DIR}/*"):
            if data.endswith(EXEMPT_CACHE_FILETYPES):
                continue
            if data not in persistent_ids:
                os.remove(data)
                _log(f"removed stray data: {data}")

    def try_clear_one_item(
        self,
        sender: rumps.MenuItem = None,
        *,
        item: ClipItem,
        keep_persistent_data=False,
        no_log=False,
    ):
        """
        If ClipItem is in ClippyApp's deque, removes from deque, optionally
        preserves temp files/data the item relied on, and removes item from GUI.
        """
        if item not in self.items:
            return
        if not no_log:
            _log(f"clearing item {item}")
        try:
            # remove item from ClippApp's item list
            self.items.remove(item)
            # clean up any memory that item was using
            if not keep_persistent_data:
                item.remove_persistent_data()
            # remove that item from the app's main menu
            del self.gui.menu[item.title]
        except KeyError as e:
            _log(f"KeyError: failed to clear item {item}: {e}")

    def clear_all_items(
        self,
        sender: rumps.MenuItem | None = None,
        *,
        respect_pins=False,
        clear_system_clip=True,
    ):
        """
        Calls try_clear_one_item on all items, optionally preserving
        pinned items, and optionally preserving current system clipboard.
        """
        if clear_system_clip:
            self.clip_manager.clear_system_clipboard()
        for item in list(self.items):
            if respect_pins and item.is_pinned:
                continue
            self.try_clear_one_item(item=item)
        self.serialize_data()

    def serialize_data(self, only_pinned: bool = True):
        """
        Serializes all ClipItems in ClippyApp's deque with
        rumps.App's default serializer (pickle), optionally
        including non-pinned items.

        Also serializes ClippyApp's id_dispatch (InvisibleStringCounter)
        to ensure future ClipItems don't overwrite old ones.
        """
        with open(SERIALIZED_FP, "wb") as f:
            if only_pinned:
                tmp_items = deque(filter(lambda i: i.is_pinned, self.items))
            else:
                tmp_items = self.items
            serializables = (self.clip_manager.id_dispatch, tmp_items)
            self.gui.serializer.dump(serializables, f)

    def try_unserialize_data(self):
        """
        Attempts to unseralize and load cached ClipItems and
        id_dispatch (InvisibleStringCounter) from SERIALIZED_FP.
        """
        try:
            with open(SERIALIZED_FP, "rb") as f:
                tmp_dispatch: InvisibleStringCounter | None = None
                tmp_items: deque[ClipItem] | None = None
                tmp_dispatch, tmp_items = self.gui.serializer.load(f)
                for item in tmp_items:
                    if not item.persistent_id:
                        continue
                    if not os.path.isfile(item.persistent_id):
                        self.clear_cache()
                        _log("Unserialization failed, cache cleared.")
                        return
                _log(f"Unserialize: {tmp_dispatch=}")
                self.clip_manager.id_dispatch = tmp_dispatch
                _log(f"Unserialize: {tmp_items=}")
                for item in reversed(tmp_items):
                    self.add_clip_item_to_top(item)
        except FileNotFoundError:
            _log("no cache found, nothing to unserialize")

    def clear_cache(self):
        """Removes serialized/cached data"""
        try:
            os.remove(SERIALIZED_FP)
        except FileNotFoundError:
            _log("no cache found, nothing to clear")

    def quit(self, sender: rumps.MenuItem = None, *, sig_type: signal.Signals = None):
        """
        Quits application and ends script, called by user pressing 'Quit Clippy'
        button or by signal handler. If signal recieved, serializes both pinned
        and non-pinned items so that working session can be recovered.
        """
        _log("Quitting application...")
        self.cleanup_unreferenced_persistent_data()
        if sig_type:
            _log(f"Recieved signal {sig_type.name}")
            self.serialize_data(only_pinned=False)
        else:
            self.clear_all_items(respect_pins=True, clear_system_clip=False)
            self.serialize_data()
        _log("data serialized")
        _log("rumps app quiting...")
        rumps.quit_application()


def heartbeat(app: ClippyApp):
    """
    Main loop that runs in a thread separate from the GUI rumps.App.

    Checks if a clip operation (e.g. re-copy, clear) occured since
    last check and handles it by ignoring the increase reported by
    ClipDataManager.has_change_count_mismatch and updates buffers.

    Then checks for "true" change in clipboard and tries to
    add new ClipItem.
    """
    _log(f"starting non-gui on native thread {threading.get_native_id()}")
    PROGRAM_CLIP_OPERATION.acquire(blocking=True, timeout=LOCK_TIMEOUT)

    while True:
        if PROGRAM_CLIP_OPERATION.locked():
            PROGRAM_CLIP_OPERATION.release()
        time.sleep(TIME_STEP)
        if not PROGRAM_CLIP_OPERATION.acquire(blocking=True, timeout=LOCK_TIMEOUT):
            _log("non-gui thread failed to get lock")

        if app.clip_manager.has_change_count_mismatch():
            app.clip_manager.update_change_count()
            if PROGRAM_CLIP_SET_EVENT.is_set():
                app.clip_manager.update_buffers
                PROGRAM_CLIP_SET_EVENT.clear()
                continue
            try:
                if new_item := app.clip_manager.get_new_item():
                    app.add_clip_item_to_top(new_item)
            except BaseException as e:
                _log(f"unknown exception in adding clip: {e}")


def main():
    """
    Entry point. Configures ClippyCache directory, ensures script run in
    the background, creates ClippyApp, creates and starts heartbeat thread,
    and runs ClippyApp.gui.
    """
    config_script_for_background_use()
    config_script_directories()

    _log(f"ClippyApp started on native thread {threading.get_native_id()}")

    app = ClippyApp(
        name=APP_NAME,
        icon=APP_MENUBAR_ICON,
        clip_manager=ClipDataManager(id_dispatch=iter(InvisibleStringCounter())),
        history_len=DEFAULT_CLIP_HISTORY,
    )

    background_thread = threading.Thread(target=heartbeat, args=[app], daemon=True)
    background_thread.start()

    try:
        app.gui.run()
    except BaseException as e:
        _log(f"unknown exception in app.gui.run: {e}")


if __name__ == "__main__":
    main()
