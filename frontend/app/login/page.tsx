"use client";

import { FormEvent, Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import TalonLogo from "@/components/TalonLogo";
import { getSupabase } from "@/lib/supabase";

function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const next = searchParams.get("next") || "/";

  const [mode, setMode] = useState<"login" | "signup">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    const supa = getSupabase();
    if (!supa) {
      setError("Supabase is not configured. Set NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY.");
      setLoading(false);
      return;
    }
    try {
      if (mode === "signup") {
        const { error: err } = await supa.auth.signUp({ email, password });
        if (err) throw err;
        const { error: signInErr } = await supa.auth.signInWithPassword({ email, password });
        if (signInErr) {
          setError("Account created. Check your email to confirm, then sign in.");
          setLoading(false);
          return;
        }
      } else {
        const { error: err } = await supa.auth.signInWithPassword({ email, password });
        if (err) throw err;
      }
      router.replace(next);
      router.refresh();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Authentication failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div
      style={{
        minHeight: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: "var(--bg)",
        padding: 24,
      }}
    >
      <div className="card" style={{ width: "min(400px, 100%)", padding: 32 }}>
        <div style={{ display: "flex", justifyContent: "center", marginBottom: 24 }}>
          <TalonLogo variant="lockup" size={44} />
        </div>
        <h1 style={{ margin: "0 0 8px", fontSize: 22, textAlign: "center" }}>
          {mode === "login" ? "Sign in to Talon" : "Create your account"}
        </h1>
        <p style={{ margin: "0 0 24px", fontSize: 13, color: "var(--text-secondary)", textAlign: "center" }}>
          Your searches and leads stay private to your account.
        </p>

        <form onSubmit={submit}>
          <label style={{ fontSize: 12, fontWeight: 600 }}>Email</label>
          <input
            type="email"
            required
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            style={{
              width: "100%",
              marginBottom: 14,
              marginTop: 6,
              padding: 10,
              borderRadius: 8,
              border: "1px solid var(--border)",
            }}
          />
          <label style={{ fontSize: 12, fontWeight: 600 }}>Password</label>
          <input
            type="password"
            required
            minLength={6}
            autoComplete={mode === "signup" ? "new-password" : "current-password"}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            style={{
              width: "100%",
              marginBottom: 16,
              marginTop: 6,
              padding: 10,
              borderRadius: 8,
              border: "1px solid var(--border)",
            }}
          />
          {error && (
            <p style={{ color: "#b91c1c", fontSize: 13, margin: "0 0 12px" }}>{error}</p>
          )}
          <button type="submit" className="hedwig-send-export" style={{ width: "100%" }} disabled={loading}>
            {loading ? "Please wait…" : mode === "login" ? "Sign in" : "Sign up"}
          </button>
        </form>

        <p style={{ marginTop: 20, fontSize: 13, textAlign: "center", color: "var(--text-muted)" }}>
          {mode === "login" ? (
            <>
              No account?{" "}
              <button type="button" className="btn-ghost" style={{ padding: 0 }} onClick={() => setMode("signup")}>
                Sign up
              </button>
            </>
          ) : (
            <>
              Already have an account?{" "}
              <button type="button" className="btn-ghost" style={{ padding: 0 }} onClick={() => setMode("login")}>
                Sign in
              </button>
            </>
          )}
        </p>
      </div>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense fallback={<div style={{ minHeight: "100vh", background: "var(--bg)" }} />}>
      <LoginForm />
    </Suspense>
  );
}
