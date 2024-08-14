from collections import Counter
import dataclasses
from io import TextIOWrapper
from pprint import pprint
from typing import Dict, Set, Tuple, Optional, TypeVar, Generic
from zipfile import ZipFile
import os
import re
import sys

from lxml import etree
from inscriptis import get_text as html_to_text
from models import *

"""
Data model notes

PartInstanceID is a fritzing modelIndex.

"""

PART_EXTENSION = '.fzp'
WIRE_MODULE_ID = 'WireModuleID'
NET_LABEL_MODULE_ID = 'NetLabelModuleID'
GROUND_MODULE_ID = 'GroundModuleID'
SCHEMATIC_LAYERS = {'schematic', 'schematicTrace'}

# These resources are usually built into the binary by Qt so I had to get them from GitHub
FZ_RESOURCES_DB_PATH = '/home/troy/Downloads/fritzing-app/resources/parts/core'
# These are installed by Fritzing outside the resource bundle for some reason
CORE_PARTS_DB_PATH = '/usr/share/fritzing/parts/core'
# These are used in some online projects
OBSOLETE_PARTS_DB_PATH = '/usr/share/fritzing/parts/obsolete'


T = TypeVar('T')
class SuffixMatcher(Generic[T]):
    """
    A data structure storing entries of an arbitrary type and allowing you to search by module ID for
    the entry whose key is the longest suffix match to the module ID.
    """

    _entries: List[Tuple[str, T]]

    def __init__(self, elems: Dict[str, T]):
        keys = list(elems.keys())

        # Make longest prefix match first
        keys.sort(key=lambda k: len(k), reverse=True)

        self._entries = [(k, elems[k]) for k in keys]

    def lookup(self, module_id: str, default: T):
        # TODO use a trie or something to make this more efficient
        for k, v in self._entries:
            if k[0] == '^' and k[1:] == module_id:  # Special syntax for exact match
                return v

            if module_id.endswith(k):
                return v
        return default


class SuffixSet(SuffixMatcher[bool]):
    def __init__(self, *elems: List[str]):
        super().__init__({k: True for k in elems})

    def has(self, module_id: str) -> bool:
        return self.lookup(module_id, False)


@dataclass
class TemplatedPartFamily:
    title: str
    desc: str
    designator_prefix: str

    display_properties: List[str]

    # This is a regex that will be matched against the module ID to extract
    # property values (for properties where the value isn't explicitly set)
    # using the corresponding named capture groups (?P<prop_name>...).
    # Unfortunately templated parts rely heavily on this mechanism in Fritzing
    # (see for example the genFZP method of pinheader.cpp).
    # An underscore in the group name will be converted to a space for the
    # property name, since group names can't contain spaces.
    id_match_pattern: str

    def matches(self, module_id: str):
        return re.compile(self.id_match_pattern).match(module_id)

# These are module IDs for core parts that aren't fully specified by their part bin
# description, and instead can be manually parameterized in the UI.
# For more on how this works see this forum post:
# https://forum.fritzing.org/t/properties-for-custom-parts/14641/2
FACTORY_PART_MODULE_ID_SUFFIXES = SuffixSet(
    'ResistorModuleID',
    'CapacitorModuleID',
    'CrystalModuleID',
    'ThermistorModuleID',
    'ZenerDiodeModuleID',
    'PotentiometerModuleID',
    'InductorModuleID',
    '2PowerModuleID',
    'ColorLEDModuleID',
    'LEDSuperfluxModuleID',
    'LEDModuleID',
    'PerfboardModuleID',
    'StripboardModuleID',
    'Stripboard2ModuleID',
    'SchematicFrameModuleID',
    'PadModuleID',
    'BlockerModuleID',
    # These below aren't technically factory parts in the Fz codebase, but they get parameterized
    # so we need to treat them that way
    'PowerLabelModuleID',
)

# Some parts have an unsuitable title (e.g. resistors say they're all 220 ohms).
FACTORY_PART_TITLE_OVERRIDES = SuffixMatcher({
    'ResistorModuleID': 'Resistor',

    # These are all titled "Blue smd LED" even though the color is customizable :/
    '^1206ColorLEDModuleID': 'SMD LED',
    '^603ColorLEDModuleID': 'SMD LED',
    '^805ColorLEDModuleID': 'SMD LED',

    # These are titled "Red LED" despite the possibility to change color
    '^5mmColorLEDModuleID': 'LED - 5mm',
    '^3mmColorLEDModuleID': 'LED - 3mm',
})

# Some parts have an unsuitable long description (e.g. capacitors say they're all 1000uf).
FACTORY_PART_LONG_DESCRIPTION_OVERRIDES = SuffixMatcher({
    'CapacitorModuleID': 'A generic capacitor',
    'ColorLEDModuleID': 'A generic LED (~1.8V)',
})


# These are parts generated by template (even more complicated than the normal factory
# parts). Also called "Part-o-matic" in some places in Fritzing. They are selected based
# on the part's family and none of them are defined in an actual fzp file; instead they
# are generated on the fly from templates. For our purposes we only care about basic
# metadata and the number of pins, so we make our own stripped down descriptions on the
# fly too.
# Important: There must be a value for "pins" for each of these!
TEMPLATED_PART_FAMILIES = [
    TemplatedPartFamily(
        # Family: "screw terminal"
        id_match_pattern=r'^screw_terminal_(?P<pins>\d+)_(?P<pin_spacing>[^_]*)',
        title='Screw terminal',
        desc='Generic screw terminal',
        designator_prefix='J',
        display_properties=['part number', 'pins', 'pin spacing'],
    ),
    TemplatedPartFamily(
        # Family: "generic IC"
        id_match_pattern=r'^generic_ic_dip_(?P<pins>\d+)_(?P<pin_spacing>[^_]*)',
        title='Generic DIP', # TODO incorporate chip label with template str
        desc='A generic DIP IC',
        designator_prefix='IC',
        display_properties=['chip label', 'part number', 'pins', 'pin spacing'],
    ),
    TemplatedPartFamily(
        # Family: "pin header"
        # TODO this can be divided into more varieties and more properties extracted; I didn't bother for now
        # see my notes on formModule and the possible options
        id_match_pattern=r'^generic.*_male_pin_header_(?P<pins>\d+)',
        title='Generic male pin header',
        desc='A generic male pin header; may be single or double row',
        designator_prefix='J',
        display_properties=['part number', 'pins'],
    ),
    TemplatedPartFamily(
        # Family: "pin header"
        # TODO this can be divided into more varieties and more properties extracted; I didn't bother for now
        # see my notes on formModule and the possible options
        id_match_pattern=r'^generic.*_female_pin_header_(?P<pins>\d+)',
        title='Generic female pin header',
        desc='A generic female pin header; may be single or double row',
        designator_prefix='J',
        display_properties=['part number', 'pins'],
    ),
    TemplatedPartFamily(
        # Family: "pin header"
        id_match_pattern=r'^generic_molex_pin_header_(?P<pins>\d+)',
        title='Generic Molex pin header',
        desc='A generic Molex pin header',
        designator_prefix='J',
        display_properties=['part number', 'pins'],
    ),
    TemplatedPartFamily(
        # Family: "pin header"
        id_match_pattern=r'^generic_shrouded_pin_header_(?P<pins>\d+)',
        title='Generic shrouded pin header',
        desc='A generic shrouded pin header',
        designator_prefix='J',
        display_properties=['part number', 'pins'],
    ),
]


# This is a list of properties to show in the description of a part even if the part
# does not have showInLabel=true for these props; all lowercase
PROPERTIES_TO_ALWAYS_DISPLAY = {'voltage'}

PROPERTY_UNITS = {
    'voltage': 'V',
    'resistance': chr(937), # Fritzing uses &#937; (Greek capital letter omega) rather than &#8486; (ohm sign) and we don't want to double up
    'power': 'W',
    'current': 'A',
}

@dataclasses.dataclass(kw_only=True)
class FzPart(Part):
    properties: Dict[str, str]
    display_properties: List[str]   # Props with showInLabel in part definition; in order; all lowercase

PartsBin = Dict[str, FzPart]

@dataclass(frozen=True, order=True)
class PinRef:
    part_instance_id: PartInstanceID
    pin_id: PinID

def create_factory_part_id(
    module_id: str,
    props: Dict[str, str]
) -> PartID:
    kv_str = ';'.join([
        f"{k}={props[k]}"
        for k in sorted(props.keys())
        if k != 'family' # Family key is a generic category and is redundant
    ])
    return f"{module_id}:{kv_str}"

def format_prop(prop_key: str, props: Dict[str, str]) -> str:
    val = props[prop_key]

    unit = PROPERTY_UNITS.get(prop_key)
    if val != "" and unit and not val.upper().endswith(unit):
        val += unit

    return val

def format_parenthetical_props(prop_values: Dict[str, str], display_properties: List[str]) -> str:
    parenthetical_props = ', '.join([
        f"{dp} {format_prop(dp, prop_values)}" for dp in display_properties
            if prop_values.get(dp) # Ignore empty string or null props
    ])

    if parenthetical_props:
        return ' (' + parenthetical_props + ')'
    else:
        return ''


def create_factory_part(
    parts_bin: PartsBin,
    module_id: str,
    props: Dict[str, str]
) -> Part:
    parent_part = parts_bin[module_id]

    # Merge parent and child properties
    new_props = dict(parent_part.properties)
    new_props.update(props)

    new_short_name = FACTORY_PART_TITLE_OVERRIDES.lookup(module_id, parent_part.short_name)

    new_short_name += format_parenthetical_props(new_props, parent_part.display_properties)

    desc = FACTORY_PART_LONG_DESCRIPTION_OVERRIDES.lookup(module_id, parent_part.description)

    new_part = dataclasses.replace(
        parts_bin[module_id],
        short_name=new_short_name,
        description=FACTORY_PART_LONG_DESCRIPTION_OVERRIDES.lookup(module_id, parent_part.description),
        part_id=create_factory_part_id(module_id, new_props),
        properties=new_props,
    )

    # For now I'm assuming the factory settings don't affect the number of pins
    # TODO verify this
    return new_part


def create_templated_part(
    family_spec: TemplatedPartFamily,
    module_id: str,
    props: Dict[str, str],
) -> Part:
    # If you think this is bad you should see how Fritzing does the same thing but in
    # dozens of lines of code :)
    combined_props = {
        k.replace('_', ' '): v
        for k, v in
            re.compile(family_spec.id_match_pattern).match(module_id).groupdict().items()
    }

    combined_props.update(props)

    # We create a new module ID here. Why? Mainly because some parts can have a "chip label"
    # property and for those we want them to end up as separate parts.
    module_id = create_factory_part_id(module_id, combined_props)

    pin_count = int(combined_props['pins'])  # This key must exist
    # TODO use local pin names if they exist
    pins = {
        f"connector{i}": PartPin(
            pin_id=f"connector{i}",
            short_name=f"{i + 1}",
            description=None,
        )
        for i in range(pin_count)
    }

    parenthetical = format_parenthetical_props(combined_props, family_spec.display_properties)
    short_name = family_spec.title + parenthetical


    return FzPart(
        part_id=module_id,
        short_name=short_name,
        description=family_spec.desc,
        pins=pins,
        designator_prefix=family_spec.designator_prefix,
        properties=combined_props,
        display_properties=family_spec.display_properties,
    )


def clean_pin_name(name: str):
    name = name.strip()
    name = re.sub(r'^pin(\d)', r'\1', name, flags=re.IGNORECASE)
    name = re.sub(r'^leg(\d)', r'\1', name, flags=re.IGNORECASE)
    name = re.sub(r'^pin ', '', name, flags=re.IGNORECASE)
    return name


def parse_part_file(fh: TextIOWrapper) -> FzPart:
    # Some of the old part files are malformed so I'm using the HTML parser to handle them
    # The HTML parser inserts an <html> and <body> tag even if there are none
    module_tag = etree.parse(fh, parser=etree.HTMLParser()).getroot().find('./body/module')

    module_id = module_tag.get('moduleid')  # HTML etree attr keys are lowercase
    short_name = module_tag.find('./title').text

    desc_tag = module_tag.find('./description')
    description = None if desc_tag is None else desc_tag.text
    if description and '<!DOCTYPE' in description:
        description = html_to_text(description)

    label_tag = module_tag.find('./label')
    # Either label_tag or label_tag.text can be None
    if label_tag is None or label_tag.text is None:
        designator_prefix = 'U'
    else:
        designator_prefix = label_tag.text

    # If the designator prefix is just a number, the parts view will be confusing
    # so we add a prefix to it
    if designator_prefix.isnumeric():
        designator_prefix = 'UN' + designator_prefix  # "UN" is arbitrary

    # If the designator prefix ends in a number, we get confusing part numbers
    # so we add an underscore to it
    if designator_prefix[-1].isnumeric():
        designator_prefix += '_'

    property_tags = module_tag.findall("./properties/property")
    properties = {
        p.get('name').lower(): p.text for p in property_tags
    }

    display_properties = [
        p.get('name').lower() # These should be case insensitive
        for p in property_tags
            if p.get("showinlabel") == "yes"
                or p.get("name").lower() in PROPERTIES_TO_ALWAYS_DISPLAY
    ]

    pins: Dict[PinID, PartPin] = {}

    for connector_tag in module_tag.findall('./connectors/connector'):
        pid = connector_tag.get('id')
        pin_short_name = clean_pin_name(connector_tag.get('name'))

        pin_desc_tag = connector_tag.find('./description')
        pin_desc = None if pin_desc_tag is None else pin_desc_tag.text
        if pin_desc and '<!DOCTYPE' in pin_desc:
            pin_desc = html_to_text(pin_desc)

        pins[pid] = PartPin(pin_id=pid, short_name=pin_short_name, description=pin_desc)

    return FzPart(
        part_id=module_id,
        short_name=short_name,
        description=description,
        pins=pins,
        designator_prefix=designator_prefix,
        properties=properties,
        display_properties=display_properties,
    )


def sort_adj(a, b):
    if a > b:
        return a, b
    else:
        return b, a


def parse_schematic(parts_bin: PartsBin, fh: TextIOWrapper) -> Schematic:
    xml_doc = etree.parse(fh)

    # First we list the wires. They're redundant for nodes in the schematic so we want to ignore them when producing
    # the final result. Another thing these all have in common is their one pin called "common".
    connector_instance_ids: Set[str] = set([
        e.get('modelIndex') for e in
            # Note: lxml's xpath doesn't support selecting attribute values directly, only nodes
            xml_doc.findall(f"./instances/instance")
            if e.get('moduleIdRef') in [NET_LABEL_MODULE_ID, WIRE_MODULE_ID, GROUND_MODULE_ID]
    ])
    net_labels: Dict[str, str] = {}  # Maps net label node instance IDs to the net's name

    schematic = Schematic()
    adjacencies: Set[Tuple[PinRef, PinRef]] = set()
    designator_counts = Counter()

    # Pre-populate a ground node and net
    net_labels[GROUND_PART_INSTANCE.part_instance_id] = GROUND_PART.short_name
    schematic.part_instances_by_id[GROUND_PART_INSTANCE.part_instance_id] = GROUND_PART_INSTANCE

    for instance in xml_doc.findall('./instances/instance'):
        module_id_ref = instance.get('moduleIdRef')
        is_net_label = module_id_ref == NET_LABEL_MODULE_ID
        is_wire = module_id_ref == WIRE_MODULE_ID
        is_ground = module_id_ref == GROUND_MODULE_ID

        schematic_view = instance.find('./views/schematicView')
        if schematic_view is None or schematic_view.get('layer') not in SCHEMATIC_LAYERS:  # This could be a PCB or breadboard-only symbol
            continue

        instance_id = instance.get('modelIndex')

        has_connection = False

        # Find all the connections and put them in the adjacency list
        for connector in schematic_view.findall('./connectors/connector'):
            if connector.get('layer') not in SCHEMATIC_LAYERS:
                continue # TODO test

            # Treat all endpoints of a wire as the same node so they end up adjacent
            if is_wire or is_net_label or is_ground:
                pin_id = 'common'
            else:
                pin_id = connector.get('connectorId')

            this_pin_ref = PinRef(
                part_instance_id=instance_id,
                pin_id=pin_id,
            )

            for connect2 in connector.findall('./connects/connect'):
                if connect2.get('layer') not in SCHEMATIC_LAYERS:
                    continue # TODO test

                has_connection = True
                c2_part_inst = connect2.get('modelIndex')
                c2_conn_id = connect2.get('connectorId')

                if c2_part_inst in connector_instance_ids:
                    c2_conn_id = 'common'

                other_pin_ref = PinRef(part_instance_id=c2_part_inst, pin_id=c2_conn_id)

                # We add these always in a sorted order since they're non-directional
                adjacencies.add(sort_adj(this_pin_ref, other_pin_ref))

        # Extract the property key-value pairs
        properties: Dict[str, str] = {
            prop_tag.get('name').lower(): prop_tag.get('value')
            for prop_tag in instance.findall("./property") or []
        }

        if is_ground:
            # All grounds are connected to the same singleton ground part, and then the parts
            # that were the schmeatic grounds from the FZ file are treated as wires, so we
            # traverse through them to reach the actual ground.
            schematic_pin_ref = PinRef(
                part_instance_id=instance_id,
                pin_id='common',
            )

            implicit_ground_net_ref = PinRef(
                part_instance_id=GROUND_PART_INSTANCE.part_instance_id,
                pin_id=list(GROUND_PART.pins.keys())[0],
            )

            adjacencies.add(sort_adj(schematic_pin_ref, implicit_ground_net_ref))

            # Note: The original ground symbol is marked as a connector already
            # (see construction of connector_instance_ids) so it will not be displayed
            # as its own part and will be traversed in the net coalescing step

        elif is_net_label:
            # Net labels are implicitly connected to all other net labels of the same name,
            # so we create a virtual wire from the net label's common pin to a node based
            # on the net name
            # NB: There is a similar label in <title> but that will have a different int
            # suffix for each instance of the same net label
            net_name = properties['label'] # TODO should I trim this?

            net_node_instance_id = f"net_ref:{net_name}"

            schematic_pin_ref = PinRef(
                part_instance_id=instance_id,
                pin_id='common',
            )
            implicit_net_ref = PinRef(
                part_instance_id=net_node_instance_id,
                pin_id='common',
            )

            adjacencies.add(sort_adj(schematic_pin_ref, implicit_net_ref))

            # Treat this fake net node as a wire
            # (note that the net node from the FZ file will already be marked as a wire
            # when we initialized connector_instance_ids above)
            connector_instance_ids.add(net_node_instance_id)

            # Record the label for later
            net_labels[net_node_instance_id] = net_name


        if is_wire or is_net_label or is_ground:
            # Don't create a part instance for wires, we'll eliminate them later
            continue

        if FACTORY_PART_MODULE_ID_SUFFIXES.has(module_id_ref):
            part = create_factory_part(parts_bin, module_id_ref, properties)
        elif module_id_ref in parts_bin:
            part = parts_bin[module_id_ref]
        else:
            # Look for a templated part
            for family_spec in TEMPLATED_PART_FAMILIES:
                if family_spec.matches(module_id_ref):
                    part = create_templated_part(family_spec, module_id_ref, properties)
                    break

            if part is None:
                raise RuntimeError(f"No spec found for part with ID {module_id_ref}")

        designator_counts[part.designator_prefix] += 1

        part_instance = PartInstance(
            part_instance_id=instance_id,
            part=part,
            designator=part.designator_prefix + str(designator_counts[part.designator_prefix])
        )

        if has_connection:
            schematic.part_instances_by_id[instance_id] = part_instance
            # Note: unconnected part will still take a designator slot for now

    # Traverse all the adjacencies to build the nets
    nets: List[Set[PinRef]] = [set([p]) for p in sorted(set([  # Start with each PinRef in its own set
        p
        for adj in adjacencies
        for p in adj
    ]))]

    while True:
        merged_something = False
        i = 0
        while i < len(nets) - 1:
            nets_to_merge = set()
            for p in nets[i]:
                for j in range(i + 1, len(nets)):
                    net2 = nets[j]
                    for q in nets[j]:
                        if sort_adj(p, q) in adjacencies:
                            nets_to_merge.add(j)
                            break

            for j in nets_to_merge:
                nets[i] = nets[i].union(nets[j])

            # Do this in a separate loop so we don't mess up indices
            nets = [n for j, n in enumerate(nets) if j not in nets_to_merge]

            if nets_to_merge:
                merged_something = True

            i += 1

        if not merged_something:
            break

    for i, net in enumerate(sorted(nets)):
        sorted_net = sorted(net)
        connections = [
            Connection(
                part_instance=schematic.part_instances_by_id[p.part_instance_id],
                pin_id=p.pin_id,
            )
            for p in sorted_net
            if p.part_instance_id not in connector_instance_ids
        ]

        if not connections:
            # This can happen if all the parts are connectors.
            # They won't be merged into another net if all the things they
            # connect to are in non-schematic layers (e.g. intermediate BB
            # buses that make the breadboard look nicer)
            continue

        net_name = next(  # If there are multiple nets we just pick one
            (net_labels[p.part_instance_id] for p in sorted_net if p.part_instance_id in net_labels),
            None
        )

        node_id = f"node{i}"
        schematic.nodes_by_id[node_id] = Node(node_id=node_id, connections=connections, label=net_name)

    return schematic


def load_core_parts() -> PartsBin:
    parts_bin: PartsBin = {}

    for dir_path in [FZ_RESOURCES_DB_PATH, CORE_PARTS_DB_PATH, OBSOLETE_PARTS_DB_PATH]:
        for filename in os.listdir(dir_path):
            if not filename.endswith(PART_EXTENSION):
                continue

            f = os.path.join(dir_path, filename)

            with open(f, 'r') as fh:
                part = parse_part_file(fh)
                parts_bin[part.part_id] = part

    return parts_bin


# TODO make this take in a file handle?
def parse_sketch(parts_bin: PartsBin, path: str) -> Schematic:
    # Note: parts_bin gets mutated; I think that's OK for this use case

    with ZipFile(path, 'r') as zf:
        fzp_files = [f for f in zf.namelist() if f.endswith(PART_EXTENSION)]
        fz_files = [f for f in zf.namelist() if f.endswith('.fz')]

        if len(fz_files) != 1:
            raise RuntimeError("Unsupported number of .fz files in archive")

        # Parse any non-core parts included in the package
        for fzp_file in fzp_files:
            with zf.open(fzp_file) as fh:
                part = parse_part_file(fh)
                parts_bin[part.part_id] = part

        # Parse the schematic file
        with zf.open(fz_files[0]) as fh:
            return parse_schematic(parts_bin, fh)
