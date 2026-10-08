// "/" opens the default market's home.
import { redirect } from "next/navigation";
import { DEFAULT_MARKET } from "../lib/ui/routes.ts";

export default function Root(): never {
  redirect(`/${DEFAULT_MARKET}`);
}
