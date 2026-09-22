/**
 * Umschalter „klassischer" ↔ „neuer" Prozess-Editor (Beta).
 *
 * Während des Umbaus (v2) laufen beide Editoren parallel; welcher greift, hängt
 * an einem pro-Browser gemerkten Flag. Modulweit EIN reaktiver Wert, damit die
 * Umschalter in beiden Editoren und der Wrapper denselben Stand teilen. Der
 * Zugriff auf localStorage ist überall in try/catch (privates Fenster, gesperrter
 * Storage) – Fehlschlag heißt schlicht „klassischer Editor".
 */
import { ref } from 'vue'

const STORAGE_KEY = 'processEditorV2'

function read(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) === '1'
  } catch {
    return false
  }
}

// Modul-Singleton: alle Aufrufer sehen denselben reaktiven Wert.
const enabled = ref(read())

export function useProcessEditorFlag() {
  function set(v: boolean) {
    enabled.value = v
    try {
      localStorage.setItem(STORAGE_KEY, v ? '1' : '0')
    } catch {
      /* Storage gesperrt – der reaktive Wert gilt trotzdem für diese Sitzung. */
    }
  }
  return { enabled, set }
}
