import { client } from './client'

export interface UserEntry {
  id: string
  displayName: string
  mail: string | null
}

export const usersApi = {
  list: () => client.get<{ data: { users: UserEntry[] } }>('/users'),
}