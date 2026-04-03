import { RouterProvider } from "react-router-dom";
import { TooltipProvider } from "@/components/ui/tooltip";
import { appRouter } from "@/app/router";

export default function App() {
  return (
    <TooltipProvider>
      <RouterProvider router={appRouter} />
    </TooltipProvider>
  );
}
