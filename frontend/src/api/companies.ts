// api/companies.ts
import { client } from './client'
export const companiesApi = {
  list: () => client.get<{ data: { companies: string[] } }>('/companies'),
}