from fritzing_parser import load_core_parts, parse_sketch
from describer import describe_as_html
import sys

from pprint import pprint

#DEFAULT_INFILE = '/home/troy/tmp/fritzing/inputs/recent_rpi_pico_simon.fzz'
DEFAULT_INFILE = '/home/troy/tmp/fritzing/inputs/net_labels.fzz'


infile = DEFAULT_INFILE
if len(sys.argv) > 1:
    infile = sys.argv[1]

parts_bin = load_core_parts()
schematic = parse_sketch(parts_bin, infile)

print(describe_as_html(schematic))
