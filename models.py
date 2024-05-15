from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set


PartID = str
PartInstanceID = str
PinID = str
NodeID = str


@dataclass
class PartPin:
    pin_id: PinID  # This may not be globally unique, must be unique per part
    short_name: str  # This will not have the word "pin" in it and should have all space trimmed
    description: Optional[str]


@dataclass
class Part:
    part_id: PartID
    short_name: str
    description: Optional[str]
    designator_prefix: str
    pins: Dict[PinID, PartPin]

    def pin_reference(pin_id: PinID) -> str:
        kind = 'lead' if len(pins) <= 3 else 'pin'

        short_name = pins[pin_id].short_name
        if short_name.isnumeric():
            return f"{kind} {short_name}"  # e.g. "lead 0", "pin 0"
        else:
            return f"the {short_name} {kind}"  # e.g. "the + lead", "the SCK / PB0 pin"


@dataclass
class PartInstance:
    """ Represents an instance of a part """
    part_instance_id: PartInstanceID
    designator: str  # e.g. C1
    part: Part


@dataclass(frozen=True)
class Connection:
    part_instance: PartInstance
    pin_id: PinID


@dataclass
class Node:
    node_id: NodeID
    connections: Set[Connection]


@dataclass
class Schematic:
    part_instances_by_id: Dict[PartInstanceID, PartInstance] = field(default_factory=dict)
    nodes_by_id: Dict[NodeID, Node] = field(default_factory=dict)
