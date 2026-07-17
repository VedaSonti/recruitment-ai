"use client";

import { Search } from "lucide-react";

export function SearchBar({
  onChange,
  placeholder,
  value,
}: {
  onChange: (value: string) => void;
  placeholder: string;
  value: string;
}) {
  return (
    <label className="flex h-12 items-center gap-3 rounded-[8px] border border-[#d8dee7] bg-white px-4 shadow-soft">
      <Search className="h-5 w-5 text-[#98a2b3]" />
      <input
        className="w-full border-0 bg-transparent text-[15px] outline-none placeholder:text-[#9ca0a8]"
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        value={value}
      />
    </label>
  );
}
