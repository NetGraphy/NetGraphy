# Built-in custom filter: classify_inventory_type
# Given an inventory item NAME string, returns the appropriate item_type enum value

def classify_inventory_type(name: str) -> str:
    """Classify a 'show inventory' NAME field into an InventoryItem.item_type enum value."""
    name_lower = name.lower()
    if "power supply" in name_lower or "psu" in name_lower:
        return "power_supply"
    if "fan" in name_lower:
        return "fan"
    if "supervisor" in name_lower or "sup" in name_lower:
        return "supervisor"
    if "line card" in name_lower or "linecard" in name_lower:
        return "line_card"
    if "nim" in name_lower or "module" in name_lower:
        return "module"
    if "sfp" in name_lower or "transceiver" in name_lower or "optic" in name_lower:
        return "optic"
    if "chassis" in name_lower:
        return "other"
    return "other"
