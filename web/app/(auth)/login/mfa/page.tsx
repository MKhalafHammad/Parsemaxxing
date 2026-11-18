"use client";

import { Suspense } from "react";

import { CodeForm } from "@/components/auth/code-form";

export default function Page() {
  return (
    <Suspense>
      <CodeForm recovery={false} />
    </Suspense>
  );
}
