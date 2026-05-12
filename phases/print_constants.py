from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm, inch

PAGE_SIZE = A4
PAGE_WIDTH, PAGE_HEIGHT = PAGE_SIZE
PAGE_MARGIN = 10 * mm

N_COLS = 4

BUBBLE_RADIUS = 2.5 * mm
BUBBLE_SPACING = 2 * mm

MARKER_SIZE = 6 * mm
MARKER_INSET = 5 * mm
MARKER_POSITIONS = [
    (MARKER_INSET, MARKER_INSET),  # bottom left
    (PAGE_WIDTH - MARKER_SIZE - MARKER_INSET, MARKER_INSET),  # bottom right
    (MARKER_INSET, PAGE_HEIGHT - MARKER_SIZE - MARKER_INSET),  # top left
    (PAGE_WIDTH - MARKER_SIZE - MARKER_INSET,
     PAGE_HEIGHT - MARKER_SIZE - MARKER_INSET)  # top right
]

TITLE_SPACING = 15 * mm