"""Permission catalogue and default role templates. Codes are `resource:action`."""

PERMISSIONS: dict[str, str] = {
    "store:read": "View stores",
    "store:write": "Create and edit stores",
    "user:read": "View users",
    "user:write": "Create and edit users",
    "role:read": "View roles",
    "role:write": "Create and edit roles",
    "audit:read": "View audit log",
    "product:read": "View products and variants",
    "product:write": "Create and edit products and variants",
    "inventory:read": "View stock and movements",
    "inventory:adjust": "Adjust stock manually",
    "purchase:read": "View purchases and suppliers",
    "purchase:write": "Record purchases and suppliers",
    "sale:create": "Create sales at the POS",
    "sale:read": "View sales and invoices",
    "sale:discount": "Apply discounts above the standard limit",
    "return:create": "Process returns and exchanges",
    "customer:read": "View customers",
    "customer:write": "Create and edit customers",
    "report:read": "View reports",
    "register:manage": "Open and close the cash register",
}

_ALL = set(PERMISSIONS)

DEFAULT_ROLES: dict[str, set[str]] = {
    "Owner": _ALL,
    "Manager": _ALL - {"user:write", "role:write", "store:write", "audit:read"},
    "Cashier": {
        "product:read",
        "inventory:read",
        "sale:create",
        "sale:read",
        "return:create",
        "customer:read",
        "customer:write",
        "register:manage",
    },
}

OWNER_ROLE = "Owner"
