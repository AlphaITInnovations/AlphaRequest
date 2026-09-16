import { client } from '@/api/client'
import type { DataResponse, User, UserProfile } from '@/types/api'

export const authApi = {
  me:             () => client.get<DataResponse<User>>('/auth/me'),
  profile:        () => client.get<DataResponse<UserProfile>>('/auth/profile'),
  refreshSession: () => client.post<DataResponse<User>>('/auth/refresh-session'),
  checkSession:   () => client.get<{ status: string }>('/auth/check'),
}