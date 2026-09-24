/**
 * Umschalter „neuer" (v2, Standard) ↔ „klassischer" Prozess-Editor.
 *
 * Seit dem Cutover ist v2 der STANDARD: ohne gemerkte Wahl greift v2. Der
 * klassische Editor bleibt als Rückfallebene über den Umschalter erreichbar; nur
 * eine ausdrücklich dort getroffene Wahl („0") hält ihn. Modulweit EIN reaktiver
 * Wert, damit Umschalter in beiden Editoren und der Wrapper denselben Stand
 * teilen. localStorage-Zugriff überall in try/catch (privates Fenster, gesperrter
 * Storage) – Fehlschlag heißt schlicht „neuer Editor".
 */
import { ref } from 'vue'

const STORAGE_KEY = 'processEditorV2'

function read(): boolean {
  try {
    // Standard = v2; nur die ausdrückliche Wahl „klassisch" ("0") schaltet zurück.
    return localStorage.getItem(STORAGE_KEY) !== '0'
  } catch {
    return true
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
