AXES = ("smells", "architecture", "contracts")
STAGES = ("discovery", "confirmation")
MAX_PACKET_UNITS = 50
FORMATS = ("ruff", "eslint", "stylelint", "sarif")
DEPENDENCY_CYCLE = "dependency-cycle"
FOLDER_CYCLE = "folder-cycle"
SINGLE_IMPORTER = "single-importer"
WIDE_FOLDER = "wide-folder"
GENERIC_FOLDER = "generic-folder"
CHANGE_COUPLING = "change-coupling"
DUPLICATE_BLOCK = "duplicate-block"

GRAPH_WIDE_RULES = frozenset(
    {DEPENDENCY_CYCLE, FOLDER_CYCLE, SINGLE_IMPORTER, WIDE_FOLDER, GENERIC_FOLDER}
)
HISTORY_RULES = frozenset({CHANGE_COUPLING})
