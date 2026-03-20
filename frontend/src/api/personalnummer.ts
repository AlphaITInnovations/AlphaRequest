// api/personalnummer.ts
import { client } from './client'
export const personalnummerApi = {
  next: () => client.get<{ data: { personalnummer: number } }>('/personalnummer/next'),
}