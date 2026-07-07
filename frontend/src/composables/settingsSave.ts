import { reactive, watch, onUnmounted, type Ref } from 'vue'

/**
 * Geteilter Speicher-Status für die Settings (Modul-Singleton).
 * - Die Shell rendert daraus EINE sticky Speicher-Leiste (dirty/saving) und ruft
 *   save()/reset() des aktiven Panels auf.
 * - Ein Panel registriert sich via useSaver(); ein Owner-Token verhindert, dass
 *   ein unmountendes Panel den Status des neuen Panels überschreibt.
 *
 * Bewusst: save/reset liegen als Modul-Variablen (NICHT in einem reactive-Objekt),
 * damit es keine subtilen Reaktivitätsprobleme mit Funktions-Properties gibt.
 */
const state = reactive({ dirty: false, saving: false })
let doSaveFn: () => void | Promise<void> = () => {}
let doResetFn: () => void = () => {}
let owner = 0
let seq = 0

/** Shell: reaktiver Status + Auslöser für Speichern/Verwerfen. */
export function useSettingsSaveBar() {
  return {
    state,
    save: () => doSaveFn(),
    reset: () => doResetFn(),
  }
}

export interface SaverOptions {
  dirty: Ref<boolean>
  save: () => void | Promise<void>
  reset: () => void
}

/** Panel: meldet dirty-Status + save/reset an. Gibt setSaving() zurück und räumt
 *  beim Unmount selbst auf. */
export function useSaver(opts: SaverOptions) {
  const id = ++seq
  owner = id
  doSaveFn = opts.save
  doResetFn = opts.reset
  state.dirty = false      // vor dem ersten echten Wechsel keine Leiste zeigen
  state.saving = false

  const stop = watch(opts.dirty, v => { if (owner === id) state.dirty = v })

  onUnmounted(() => {
    stop()
    if (owner === id) {
      owner = 0
      doSaveFn = () => {}
      doResetFn = () => {}
      state.dirty = false
      state.saving = false
    }
  })

  return { setSaving: (s: boolean) => { if (owner === id) state.saving = s } }
}
