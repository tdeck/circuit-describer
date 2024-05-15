from collections import Counter
from io import TextIOWrapper
from pprint import pprint
from typing import Dict, Set, Tuple
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
SCHEMATIC_LAYERS = {'schematic', 'schematicTrace'}

CORE_PARTS_DB_PATH = '/usr/share/fritzing/parts/core'


PartsBin = Dict[str, Part]

@dataclass(frozen=True, order=True)
class PinRef:
    part_instance_id: PartInstanceID
    pin_id: PinID


def clean_pin_name(name: str):
    name = name.strip()
    name = re.sub(r'^pin(\d)', '\1', name, flags=re.IGNORECASE)
    name = re.sub(r'^pin ', '', name, flags=re.IGNORECASE)
    return name


def parse_parts_file(fh: TextIOWrapper) -> Part:
    module_tag = etree.parse(fh).getroot()
    
    module_id = module_tag.get('moduleId')
    short_name = module_tag.find('./title').text

    desc_tag = module_tag.find('./description')
    description = None if desc_tag is None else desc_tag.text
    if description and '<!DOCTYPE' in description:
        description = html_to_text(description)

    label_tag = module_tag.find('./label')
    designator_prefix = 'U' if label_tag is None else label_tag.text

    pins: Dict[PinID, PartPin] = {}

    for connector_tag in module_tag.findall('./connectors/connector'):
        pid = connector_tag.get('id')
        pin_short_name = clean_pin_name(connector_tag.get('name'))

        pin_desc_tag = connector_tag.find('./description')
        pin_desc = None if pin_desc_tag is None else pin_desc_tag.text
        if pin_desc and '<!DOCTYPE' in pin_desc:
            pin_desc = html_to_text(pin_desc)

        pins[pid] = PartPin(pin_id=pid, short_name=pin_short_name, description=pin_desc)

    return Part(
        part_id=module_id,
        short_name=short_name,
        description=description,
        pins=pins,
        designator_prefix=designator_prefix
    )


def sort_adj(a, b):
    if a > b:
        return a, b
    else:
        return b, a


def parse_schematic(parts_bin: PartsBin, fh: TextIOWrapper) -> Schematic:
    xml_doc = etree.parse(fh)

    # First we list the wires. They're redundant for nodes in the schematic so we want to ignore them
    wire_instance_ids: Set[str] = set([
        e.get('modelIndex') for e in
            # Note: lxml's xpath doesn't support selecting attribute values directly, only nodes
            xml_doc.findall(f"./instances/instance[@moduleIdRef='{WIRE_MODULE_ID}']")
    ])

    schematic = Schematic()
    adjacencies: Set[Tuple[PinRef, PinRef]] = set()
    designator_counts = Counter()

    for instance in xml_doc.findall('./instances/instance'):
        module_id_ref = instance.get('moduleIdRef')
        is_wire = module_id_ref == WIRE_MODULE_ID

        schematic_view = instance.find('./views/schematicView')
        if not schematic_view or schematic_view.get('layer') not in SCHEMATIC_LAYERS:  # This could be a PCB or breadboard-only symbol
            continue

        instance_id = instance.get('modelIndex')

        has_connection = False

        # Find all the connections and put them in the adjacency list
        for connector in schematic_view.findall('./connectors/connector'):
            # Treat all endpoints of a wire as the same node so they end up adjacent
            pin_id = 'common' if is_wire else connector.get('connectorId')

            this_pin_ref = PinRef(
                part_instance_id=instance_id,
                pin_id=pin_id,
            )

            for connect2 in connector.findall('./connects/connect'):
                has_connection = True
                c2_part_inst = connect2.get('modelIndex')
                c2_conn_id = connect2.get('connectorId')

                if c2_part_inst in wire_instance_ids:
                    c2_conn_id = 'common'

                other_pin_ref = PinRef(part_instance_id=c2_part_inst, pin_id=c2_conn_id)

                # We add these always in a sorted order since they're non-directional
                adjacencies.add(sort_adj(this_pin_ref, other_pin_ref))

        if is_wire:
            # Don't create a part instance for wires, we'll eliminate them later
            continue

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
        connections = [
            Connection(
                part_instance=schematic.part_instances_by_id[p.part_instance_id],
                pin_id=p.pin_id,
            )
            for p in sorted(net)
            if p.part_instance_id not in wire_instance_ids
        ]

        node_id = f"node{i}"
        schematic.nodes_by_id[node_id] = Node(node_id=node_id, connections=connections)

    return schematic


def load_core_parts() -> PartsBin:
    parts_bin: PartsBin = {}

    for filename in os.listdir(CORE_PARTS_DB_PATH):
        if not filename.endswith(PART_EXTENSION):
            continue

        f = os.path.join(CORE_PARTS_DB_PATH, filename)

        with open(f, 'r') as fh:
            part = parse_parts_file(fh)
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
                part = parse_parts_file(fh)
                parts_bin[part.part_id] = part

        # Parse the schematic file
        with zf.open(fz_files[0]) as fh:
            return parse_schematic(parts_bin, fh)
