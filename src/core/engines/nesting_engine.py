import logging
from abc import ABC, abstractmethod
from typing import List

from rectpack import SORT_AREA, PackingBin, PackingMode, newPacker
from rectpack.guillotine import GuillotineBssfSas
from rectpack.maxrects import MaxRectsBssf

from src.core.models.domain import FileItem, JobSettings, PlacedItem, PreflightStatus, Sheet

logger = logging.getLogger(__name__)


class NestingStrategy(ABC):
    """
    Abstract strategy for nesting a list of FileItems into Sheets.
    """

    @abstractmethod
    def pack(self, items: List[FileItem], settings: JobSettings) -> List[Sheet]:
        """
        Pack items into sheets.
        """
        pass


class RectpackNestingStrategy(NestingStrategy):
    """
    Implementation of NestingStrategy using the rectpack library.
    Supports MaxRects (default) and Guillotine algorithms.
    """

    def __init__(self, algo_type: str = "maxrects"):
        self.algo_type = algo_type

    def pack(self, items: List[FileItem], settings: JobSettings) -> List[Sheet]:
        if not items:
            return []

        # Determine the packing algorithm
        pack_algo = MaxRectsBssf if self.algo_type == "maxrects" else GuillotineBssfSas

        # Initialize packer
        # Offline mode means we add all rects before calling pack()
        packer = newPacker(
            mode=PackingMode.Offline,
            bin_algo=PackingBin.BFF,
            pack_algo=pack_algo,
            sort_algo=SORT_AREA,
            rotation=settings.allow_rotation,
        )

        gap = settings.gap_mm

        # 1. Expand items by quantity and add them to the packer
        # We need to map rectpack ID back to the original FileItem.
        # Since we might have multiple copies of the same FileItem (due to quantity),
        # we can just use the item.id (UUID) as the rect ID, as rectpack allows duplicate IDs or we can keep a mapping.
        # Actually rectpack stores whatever we pass as `rid`.

        # We also need a way to look up the original FileItem to know its original dimensions
        # because the nested dimensions include the gap.
        item_lookup = {}
        for item in items:
            item_lookup[item.id] = item
            rect_w = item.width_mm + gap
            rect_h = item.height_mm + gap
            for _ in range(item.quantity):
                packer.add_rect(rect_w, rect_h, rid=item.id)

        # 2. Add bins
        # We don't know exactly how many bins we need.
        # A safe upper bound is to add one bin per item just in case.
        # rectpack handles using only the necessary bins if we use a list of bins.
        # PackingBin.BFF (Best Fit First) or similar will pack into the first bins efficiently.
        bin_w = settings.sheet_width_mm + gap
        bin_h = settings.sheet_height_mm + gap

        # Count total elements
        total_elements = sum(item.quantity for item in items)
        for _ in range(total_elements):
            packer.add_bin(bin_w, bin_h)

        # 3. Pack
        logger.info(f"Starting packing for {total_elements} items using {self.algo_type}...")
        packer.pack()

        # Check if all items were packed
        # packer.rect_list() returns all packed rects
        packed_count = len(packer.rect_list())
        if packed_count < total_elements:
            logger.warning(f"Could not pack all items! {packed_count}/{total_elements} packed.")

        # 4. Extract into Sheets
        sheets: List[Sheet] = []
        for i, bin in enumerate(packer):
            sheet = Sheet(
                job_id=items[0].job_id
                if items
                else None,  # Assuming all items belong to the same job
                sheet_number=i + 1,
                width_mm=settings.sheet_width_mm,
                height_mm=settings.sheet_height_mm,
            )

            placed_area = 0.0

            for rect in bin:
                # rect: x, y, width, height, rid
                file_item = item_lookup[rect.rid]

                # The rectpack width/height include the gap.
                # The original dimensions were file_item.width_mm and file_item.height_mm.
                # If rect.width == file_item.width_mm + gap, it wasn't rotated.
                # Due to floating point precision, we check with a small tolerance or just compare roughly.
                # Actually, a safer way to check rotation:
                w_orig = file_item.width_mm + gap
                h_orig = file_item.height_mm + gap

                # Check if it was rotated
                is_rotated = False
                if abs(rect.width - h_orig) < 0.1 and abs(rect.height - w_orig) < 0.1:
                    if abs(rect.width - w_orig) > 0.1:  # It's not a square
                        is_rotated = True

                # Actual drawn dimensions (removing the gap)
                actual_w = file_item.height_mm if is_rotated else file_item.width_mm
                actual_h = file_item.width_mm if is_rotated else file_item.height_mm

                placed_item = PlacedItem(
                    file_item_id=file_item.id,
                    source_path=file_item.path,
                    x_mm=rect.x,
                    y_mm=rect.y,
                    width_mm=actual_w,
                    height_mm=actual_h,
                    rotated=is_rotated,
                )
                sheet.items.append(placed_item)
                placed_area += actual_w * actual_h

            # Calculate fill rate based on the true sheet area (without gap)
            sheet_area = settings.sheet_width_mm * settings.sheet_height_mm
            sheet.fill_rate = (placed_area / sheet_area) * 100.0 if sheet_area > 0 else 0.0
            sheets.append(sheet)

        logger.info(f"Nesting completed: {len(sheets)} sheets generated.")
        return sheets


class ShelfNestingStrategy(NestingStrategy):
    """
    Shelf Best-Fit Decreasing Height packing.

    Items are sorted tallest-first and packed into horizontal rows ("shelves")
    that span the sheet; every item in a row sits on the same y and the row's
    height is fixed by the first (tallest) item placed in it. This produces a
    visually uniform, row-aligned layout — unlike MaxRects/Guillotine, which
    stagger items at irregular offsets — while still trying to maximize space
    usage: each item's rotation is decided at placement time (not locked in
    upfront), so it can flip to whichever orientation lets it join an existing
    row, and only falls back to "smallest new row" as a tie-break when no
    existing row fits it in either orientation.
    """

    @staticmethod
    def _valid_orientations(width_mm: float, height_mm: float, allow_rotation: bool, sheet_w: float, sheet_h: float):
        """Returns every (w, h, rotated) orientation that fits the sheet at all
        (1 or 2 entries), or an empty list if the item can't fit in any."""
        candidates = [(width_mm, height_mm, False)]
        if allow_rotation and height_mm != width_mm:
            candidates.append((height_mm, width_mm, True))
        return [c for c in candidates if c[0] <= sheet_w and c[1] <= sheet_h]

    @staticmethod
    def _grid_capacity(w: float, h: float, gap: float, sheet_w: float, sheet_h: float) -> int:
        """Estimates how many same-shape items a full sheet could hold at this
        orientation (simple grid, ignoring the current cursor position). Used
        to pick a new row's orientation: neither "minimize height" nor
        "minimize width" is uniformly better — e.g. two items each about half
        the sheet's width pack best kept wide (2 per row), while wide-but-short
        cards pack best kept in their natural, wider orientation too (more
        columns) rather than rotated tall to save height. Estimating overall
        grid density picks whichever orientation actually favors the sheet's
        proportions."""
        cols = max(1, int((sheet_w + gap) // (w + gap)))
        rows = max(1, int((sheet_h + gap) // (h + gap)))
        return cols * rows

    def pack(self, items: List[FileItem], settings: JobSettings) -> List[Sheet]:
        if not items:
            return []

        gap = settings.gap_mm
        sheet_w = settings.sheet_width_mm
        sheet_h = settings.sheet_height_mm
        job_id = items[0].job_id

        rects = []
        skipped = 0
        for item in items:
            orientations = self._valid_orientations(
                item.width_mm, item.height_mm, settings.allow_rotation, sheet_w, sheet_h
            )
            if not orientations:
                skipped += item.quantity
                continue
            for _ in range(item.quantity):
                rects.append({"item": item, "orientations": orientations})

        total_elements = sum(item.quantity for item in items)
        if skipped:
            logger.warning(
                f"Could not pack all items! {len(rects)}/{total_elements} packed "
                f"({skipped} too large for the sheet in any orientation)."
            )

        # Decreasing Height: tallest items placed first (using each item's
        # tallest available orientation), so each new shelf's fixed height is
        # set by the tallest item that will ever need it.
        rects.sort(key=lambda r: max(o[1] for o in r["orientations"]), reverse=True)

        sheets: List[Sheet] = []
        shelves: List[dict] = []
        cursor_y = 0.0

        def open_sheet():
            nonlocal shelves, cursor_y
            sheets.append(
                Sheet(job_id=job_id, sheet_number=len(sheets) + 1, width_mm=sheet_w, height_mm=sheet_h)
            )
            shelves = []
            cursor_y = 0.0

        def open_shelf(height: float):
            nonlocal cursor_y
            needed_y = cursor_y + (gap if shelves else 0.0)
            if needed_y + height > sheet_h:
                open_sheet()
                needed_y = 0.0
            shelf = {"y": needed_y, "height": height, "used_width": 0.0}
            shelves.append(shelf)
            cursor_y = needed_y + height
            return shelf

        open_sheet()

        for r in rects:
            # Best-fit across every existing shelf AND every valid orientation:
            # an item can rotate specifically to slot into a row it wouldn't
            # otherwise fit, instead of always claiming a fresh row.
            best = None  # (shelf, w, h, rotated, waste)
            for shelf in shelves:
                base_x = shelf["used_width"] + (gap if shelf["used_width"] > 0 else 0.0)
                for w, h, rotated in r["orientations"]:
                    if base_x + w <= sheet_w and h <= shelf["height"]:
                        waste = shelf["height"] - h
                        if best is None or waste < best[4]:
                            best = (shelf, w, h, rotated, waste)

            if best is None:
                # No existing shelf works in any orientation — open a new one,
                # in whichever orientation packs this shape most densely
                # against the sheet's actual proportions (see _grid_capacity).
                w, h, rotated = max(
                    r["orientations"], key=lambda o: self._grid_capacity(o[0], o[1], gap, sheet_w, sheet_h)
                )
                shelf = open_shelf(h)
            else:
                shelf, w, h, rotated, _ = best

            x = shelf["used_width"] + (gap if shelf["used_width"] > 0 else 0.0)
            sheets[-1].items.append(
                PlacedItem(
                    file_item_id=r["item"].id,
                    source_path=r["item"].path,
                    x_mm=x,
                    y_mm=shelf["y"],
                    width_mm=w,
                    height_mm=h,
                    rotated=rotated,
                )
            )
            shelf["used_width"] = x + w

        sheet_area = sheet_w * sheet_h
        for s in sheets:
            placed_area = sum(pi.width_mm * pi.height_mm for pi in s.items)
            s.fill_rate = (placed_area / sheet_area) * 100.0 if sheet_area > 0 else 0.0

        sheets = [s for s in sheets if s.items]
        for i, s in enumerate(sheets):
            s.sheet_number = i + 1

        logger.info(f"Shelf nesting completed: {len(sheets)} sheets generated.")
        return sheets


class NestingEngine:
    """
    Main engine for placing files on print sheets.
    """

    def __init__(self, strategy: NestingStrategy):
        self.strategy = strategy

    def process(self, items: List[FileItem], settings: JobSettings) -> List[Sheet]:
        """
        Takes a list of FileItems and JobSettings, and returns a list of configured Sheets.

        Margin handling lives here rather than in each strategy: the strategy
        packs into a sheet shrunk by 2*margin on each axis (so it never places
        anything closer to the edge than the margin), then every resulting
        PlacedItem is shifted by +margin and the Sheet's own width/height are
        restored to the full, unshrunk size — the margin just ends up as
        empty space around the packed area. This keeps ShelfNestingStrategy /
        RectpackNestingStrategy untouched (and their existing tests valid).
        """
        # Only nest items that are OK or WARNING (already corrected)
        # In a real workflow, we might only pass items with PreflightStatus.OK.
        valid_items = [
            item
            for item in items
            if item.preflight_status in (PreflightStatus.OK, PreflightStatus.WARNING)
        ]

        margin = settings.margin_mm or 0.0
        if margin <= 0:
            return self.strategy.pack(valid_items, settings)

        usable_w = settings.sheet_width_mm - 2 * margin
        usable_h = settings.sheet_height_mm - 2 * margin
        if usable_w <= 0 or usable_h <= 0:
            logger.warning(
                f"Margin {margin}mm leaves no usable space on a "
                f"{settings.sheet_width_mm}x{settings.sheet_height_mm}mm sheet."
            )
            return []

        usable_settings = settings.model_copy(
            update={"sheet_width_mm": usable_w, "sheet_height_mm": usable_h}
        )
        sheets = self.strategy.pack(valid_items, usable_settings)

        for sheet in sheets:
            sheet.width_mm = settings.sheet_width_mm
            sheet.height_mm = settings.sheet_height_mm
            for placed_item in sheet.items:
                placed_item.x_mm += margin
                placed_item.y_mm += margin
            # fill_rate was computed against the shrunk usable area; recompute
            # against the true full sheet area to reflect the margin correctly.
            sheet_area = settings.sheet_width_mm * settings.sheet_height_mm
            placed_area = sum(pi.width_mm * pi.height_mm for pi in sheet.items)
            sheet.fill_rate = (placed_area / sheet_area) * 100.0 if sheet_area > 0 else 0.0

        return sheets
