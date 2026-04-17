import { client } from '@/api/client'
import type { DataResponse, User } from '@/types/ticket'

export const authApi = {
  me:             () => client.get<DataResponse<User>>('/auth/me'),
  refreshSession: () => client.post<DataResponse<User>>('/auth/refresh-session'),
  checkSession:   () => client.get<{ status: string }>('/auth/check'),
}