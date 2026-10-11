"use client";

import { createContext, useContext } from "react";

export type User = { username: string; role: "owner" | "member" | "viewer"; slug: string; name: string };
export type Auth = { mode: "local" | "cloud"; authenticated: boolean; user: User | null };
export const AuthContext = createContext<Auth>({ mode: "local", authenticated: true, user: null });
export const useAuth = () => useContext(AuthContext);
