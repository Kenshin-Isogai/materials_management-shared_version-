import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Command,
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
} from "@/components/ui/command";

type NavItem = {
  label: string;
  to: string;
  group: string;
  keywords?: string[];
};

const NAV_ITEMS: NavItem[] = [
  { label: "Dashboard", to: "/", group: "Navigation", keywords: ["home", "overview"] },
  { label: "Projects", to: "/projects", group: "Planning", keywords: ["project", "demand"] },
  { label: "Project Overview", to: "/projects/overview", group: "Planning", keywords: ["summary", "pipeline"] },
  { label: "Planning Board", to: "/projects/board", group: "Planning", keywords: ["workspace", "allocation", "board"] },
  { label: "Procurement", to: "/procurement", group: "Planning", keywords: ["purchase", "shortage"] },
  { label: "BOM Analysis", to: "/bom", group: "Planning", keywords: ["bill of materials", "assembly"] },
  { label: "Items", to: "/items", group: "Inventory", keywords: ["search", "catalog", "item"] },
  { label: "Locations", to: "/locations", group: "Inventory", keywords: ["warehouse", "storage"] },
  { label: "Stock Snapshot", to: "/snapshot", group: "Inventory", keywords: ["inventory", "stock level"] },
  { label: "Movements", to: "/movements", group: "Inventory", keywords: ["inbound", "outbound", "transfer"] },
  { label: "Reservations", to: "/reservations", group: "Inventory", keywords: ["reserve", "allocation"] },
  { label: "Purchase Orders", to: "/orders", group: "Purchasing", keywords: ["order", "import", "quotation"] },
  { label: "Arrivals", to: "/arrival", group: "Purchasing", keywords: ["delivery", "receive"] },
  { label: "Master Data", to: "/master", group: "Admin", keywords: ["supplier", "category", "location"] },
  { label: "Users", to: "/users", group: "Admin", keywords: ["account", "permission"] },
  { label: "Audit Log", to: "/audit", group: "Admin", keywords: ["history", "change log"] },
];

export function CommandPalette() {
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();

  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        setOpen((prev) => !prev);
      }
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, []);

  function handleSelect(to: string) {
    setOpen(false);
    navigate(to);
  }

  const groups = [...new Set(NAV_ITEMS.map((item) => item.group))];

  return (
    <CommandDialog open={open} onOpenChange={setOpen}>
      <Command>
        <CommandInput placeholder="Type to search pages..." />
        <CommandList>
          <CommandEmpty>No results found.</CommandEmpty>
          {groups.map((group, idx) => (
            <span key={group}>
              {idx > 0 && <CommandSeparator />}
              <CommandGroup heading={group}>
                {NAV_ITEMS.filter((item) => item.group === group).map((item) => (
                  <CommandItem
                    key={item.to}
                    value={`${item.label} ${(item.keywords ?? []).join(" ")}`}
                    onSelect={() => handleSelect(item.to)}
                  >
                    {item.label}
                  </CommandItem>
                ))}
              </CommandGroup>
            </span>
          ))}
        </CommandList>
      </Command>
    </CommandDialog>
  );
}
