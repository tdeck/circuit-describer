from fritzing_parser import load_core_parts, parse_sketch
from describer import describe_as_html

from pprint import pprint

#INFILE = '/home/troy/tmp/fritzing/inputs/recent_rpi_pico_simon.fzz'
INFILE = '/home/troy/tmp/fritzing/inputs/net_labels.fzz'

parts_bin = load_core_parts()
schematic = parse_sketch(parts_bin, INFILE)

print(describe_as_html(schematic))
