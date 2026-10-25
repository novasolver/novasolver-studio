import { forwardRef, type ButtonHTMLAttributes } from "react";
import { cn } from "./cn";

type Variant = "primary" | "secondary" | "ghost" | "danger";
type Size = "sm" | "md" | "lg" | "icon" | "icon-sm";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
}

// Primary is near-black (light) / near-white (dark), not the brand hue: one per view.
const VARIANTS: Record<Variant, string> = {
  primary: "bg-primary text-primary-ink font-medium hover:opacity-90",
  secondary: "border border-line-strong text-fg font-medium hover:bg-hover active:bg-active",
  ghost: "text-fg-2 hover:text-fg hover:bg-hover active:bg-active",
  danger: "border border-line-strong text-red font-medium hover:bg-red-soft",
};

const SIZES: Record<Size, string> = {
  sm: "h-7 px-2.5 text-label gap-1.5",
  md: "h-8 px-3 text-body gap-2",
  lg: "h-9 px-3.5 text-body gap-2",
  icon: "h-8 w-8 justify-center",
  "icon-sm": "h-7 w-7 justify-center",
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "secondary", size = "md", className, type = "button", ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      className={cn(
        "inline-flex items-center rounded-[6px] whitespace-nowrap select-none",
        "transition-[background-color,color,opacity,transform] duration-[var(--dur-1)] ease-[var(--ease-out)] active:translate-y-[0.5px]",
        "disabled:opacity-50 disabled:pointer-events-none",
        VARIANTS[variant],
        SIZES[size],
        className,
      )}
      {...rest}
    />
  );
});
