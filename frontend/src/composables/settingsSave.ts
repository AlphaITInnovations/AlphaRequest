import { reactive, inject, provide, type InjectionKey } from 'vue'

/**
 * Geteilter Speicher-Status für die Settings: Die Shell stellt einen reaktiven
 * Zustand bereit, die aktive Panel-Komponente meldet dort ihren „dirty"-Status
 * und ihre save()/reset()-Funktionen an. Die Shell rendert daraus EINE sticky
 * Speicher-Leiste unten. So gibt es genau einen konsistenten Speicherweg.
 */
export interface SettingsSaveState {
  dirty: boolean
  saving: boolean
  save: () => void | Promise<void>
  reset: () => void
}

const KEY: InjectionKey<SettingsSaveState> = Symbol('settingsSave')

function _defaults(): SettingsSaveState {
  return { dirty: false, saving: false, save: () => {}, reset: () => {} }
}

/** In der Shell aufrufen. Gibt den reaktiven Zustand für die Speicher-Leiste zurück. */
export function provideSettingsSave(): SettingsSaveState {
  const state = reactive<SettingsSaveState>(_defaults())
  provide(KEY, state)
  return state
}

/** In einem Panel aufrufen. Meldet sich beim Zustand an und räumt beim Unmount auf. */
export function useSettingsSave(): SettingsSaveState {
  const s = inject(KEY)
  if (!s) throw new Error('provideSettingsSave() fehlt in einem Vorfahren')
  return s
}

/** Zustand auf Default zurücksetzen (Panel-Unmount / Sektionswechsel). */
export function resetSettingsSave(s: SettingsSaveState) {
  Object.assign(s, _defaults())
}
