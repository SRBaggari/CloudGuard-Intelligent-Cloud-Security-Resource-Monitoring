import { Compass } from "lucide-react";
import { Link } from "react-router-dom";
import { EmptyState } from "@/components/ui";

export default function NotFound() {
  return (
    <EmptyState icon={<Compass className="size-5" />} title="Page not found" message="The page you requested does not exist."
      action={<Link to="/" className="text-sm font-medium text-accent hover:underline">Back to dashboard</Link>} />
  );
}
