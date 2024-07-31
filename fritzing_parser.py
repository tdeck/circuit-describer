from collections import Counter
import dataclasses
from io import TextIOWrapper
from pprint import pprint
from typing import Dict, Set, Tuple, Optional
from zipfile import ZipFile
import os
import re

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
SCHEMATIC_LAYERS = {'schematic', 'schematicTrace'}

# These resources are usually built into the binary by Qt so I had to get them from GitHub
FZ_RESOURCES_DB_PATH = '/home/troy/Downloads/fritzing-app/resources/parts/core'
# These are installed by Fritzing outside the resource bundle for some reason
CORE_PARTS_DB_PATH = '/usr/share/fritzing/parts/core'
# These are used in some online projects
OBSOLETE_PARTS_DB_PATH = '/usr/share/fritzing/parts/obsolete'


# These are module IDs for core parts that aren't fully specified by their part bin
# description, and instead can be manually parameterized in the UI.
# For more on how this works see this forum post:
# https://forum.fritzing.org/t/properties-for-custom-parts/14641/2
FACTORY_PART_MODULE_ID_SUFFIXES = {
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
}

# Some parts have an unsuitable long description (e.g. capacitors say they're all 1000uf).
# The part's properties will be passed in as the 'props' dict for a string.format() call
FACTORY_PART_LONG_DESCRIPTION_OVERRIDES = {
    'CapacitorModuleID': 'A generic capacitor',
}

# This is a list of properties to show in the description of a part even if the part
# does not have showInLabel=true for these props; all lowercase
PROPERTIES_TO_ALWAYS_DISPLAY = {'voltage'}

@dataclasses.dataclass(kw_only=True)
class FzPart(Part):
    display_properties: List[str]   # Props with showInLabel in part definition; in order; all lowercase

PartsBin = Dict[str, FzPart]

@dataclass(frozen=True, order=True)
class PinRef:
    part_instance_id: PartInstanceID
    pin_id: PinID

def is_factory_part(module_id: str) -> bool:
    # TODO this is slow; use something more optimal
    return any((module_id.endswith(s) for s in FACTORY_PART_MODULE_ID_SUFFIXES))

def get_factory_part_override_desc(module_id: str) -> Optional[str]:
    return next(
        (v for k, v in FACTORY_PART_LONG_DESCRIPTION_OVERRIDES.items() if module_id.endswith(k)),
        None  # Default
    )

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

    if prop_key == 'voltage' and not val.upper().endswith('V'):
        # Fritzing *does* have a special case for properties called 'voltage' to make them editable,
        # (in SymbolPaletteItem) but doesn't assign units to them. Since this is such a common
        # property and we want it to be as readable as possible, we append a unit if there isn't one
        val += 'V'

    return val


def create_factory_part(
    parts_bin: PartsBin,
    module_id: str,
    props: Dict[str, str]
) -> Part:
    parent_part = parts_bin[module_id]

    parenthetical_props = ', '.join([
        f"{dp} {format_prop(dp, props)}" for dp in parent_part.display_properties
            if props[dp] != ""
    ])

    if parenthetical_props:
        new_short_name = parent_part.short_name + ' (' + parenthetical_props + ')'
    else:
        new_short_name = parent_part.short_name

    desc = get_factory_part_override_desc(module_id) or parent_part.description

    # TODO should I do something to the description?
    new_part = dataclasses.replace(
        parts_bin[module_id],
        short_name=new_short_name,
        description=desc,
        part_id=create_factory_part_id(module_id, props)
    )

    # For now I'm assuming the factory settings don't affect the number of pins
    # TODO verify this
    return new_part


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
    designator_prefix = 'U' if label_tag is None else label_tag.text

    display_properties = [
        p.get('name').lower() # These should be case insensitive
        for p in module_tag.findall("./properties/property")
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
            if e.get('moduleIdRef') in [NET_LABEL_MODULE_ID, WIRE_MODULE_ID]
    ])
    net_labels: Dict[str, str] = {}  # Maps net label node instance IDs to the net's name

    schematic = Schematic()
    adjacencies: Set[Tuple[PinRef, PinRef]] = set()
    designator_counts = Counter()

    for instance in xml_doc.findall('./instances/instance'):
        module_id_ref = instance.get('moduleIdRef')
        is_net_label = module_id_ref == NET_LABEL_MODULE_ID
        is_wire = module_id_ref == WIRE_MODULE_ID

        schematic_view = instance.find('./views/schematicView')
        if not schematic_view or schematic_view.get('layer') not in SCHEMATIC_LAYERS:  # This could be a PCB or breadboard-only symbol
            continue

        instance_id = instance.get('modelIndex')

        has_connection = False

        # Find all the connections and put them in the adjacency list
        for connector in schematic_view.findall('./connectors/connector'):
            if connector.get('layer') not in SCHEMATIC_LAYERS:
                continue # TODO test

            # Treat all endpoints of a wire as the same node so they end up adjacent
            if is_wire or is_net_label:
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

        if is_net_label:
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

            # Treat this as a wire too
            connector_instance_ids.add(net_node_instance_id)

            # Record the label for later
            net_labels[net_node_instance_id] = net_name


        if is_wire or is_net_label:
            # Don't create a part instance for wires, we'll eliminate them later
            continue

        if is_factory_part(module_id_ref):
            part = create_factory_part(parts_bin, module_id_ref, properties)
        else:
            part = parts_bin[module_id_ref]

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
