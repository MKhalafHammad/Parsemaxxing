// Sign-in, MFA and setup: product name only, no navigation, nothing technical.
export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <header className="mx-auto flex max-w-md px-4 pt-10">
        <p className="bg-gradient-to-r from-[#c4b5fd] via-[#7dd3fc] to-[#f0abfc] bg-clip-text text-2xl font-bold tracking-tight text-transparent">
          Parsemaxxing
        </p>
      </header>
      <main id="main" className="mx-auto grid max-w-md gap-4 px-4 py-6">
        {children}
      </main>
    </>
  );
}
