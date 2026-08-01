// Proyecto raíz (T-FB017-US01-01): sin lógica de negocio propia aquí — la
// única responsabilidad de este módulo es declarar los plugins de Android/
// Kotlin/Compose que el módulo `:app` aplica. Toda decisión de dominio
// (validaciones, heurística del Critic, transiciones de estado) vive en
// el backend (FB-016) — ver docstring de MainActivity.kt para el criterio
// de aceptación explícito de US-FB017-01 ("ninguna decisión de dominio
// vive en el código de la app").
plugins {
    id("com.android.application") version "8.5.2" apply false
    id("org.jetbrains.kotlin.android") version "1.9.24" apply false
}
