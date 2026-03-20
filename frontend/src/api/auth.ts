
// ── api/auth.ts ────────────────────────────────────────────────────────────────
import type { DataResponse, User } from '@/types/ticket'
import {client} from "@/api/client.ts";

export const authApi = {
  me: () => client.get<DataResponse<User>>('/auth/me'),
}
