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


class NestingEngine:
    """
    Main engine for placing files on print sheets.
    """

    def __init__(self, strategy: NestingStrategy):
        self.strategy = strategy

    def process(self, items: List[FileItem], settings: JobSettings) -> List[Sheet]:
        """
        Takes a list of FileItems and JobSettings, and returns a list of configured Sheets.
        """
        # Only nest items that are OK or WARNING (already corrected)
        # In a real workflow, we might only pass items with PreflightStatus.OK.
        valid_items = [
            item
            for item in items
            if item.preflight_status in (PreflightStatus.OK, PreflightStatus.WARNING)
        ]

        return self.strategy.pack(valid_items, settings)
