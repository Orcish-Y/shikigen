// shadcn/ui new-york-v4; source and local adaptations: frontend/component-libraries.md.
import type { ComponentProps } from "react";
import { cn } from "@/lib/utils";

function Textarea({ className, ...props }: ComponentProps<"textarea">) {
  return (
    <textarea data-slot="textarea" className={cn(
      "block min-h-12 w-full rounded-md border border-input bg-background px-3 py-2 text-sm placeholder:text-muted-foreground disabled:cursor-not-allowed disabled:opacity-50 aria-invalid:border-destructive",
      className,
    )} {...props} />
  );
}

export { Textarea };
