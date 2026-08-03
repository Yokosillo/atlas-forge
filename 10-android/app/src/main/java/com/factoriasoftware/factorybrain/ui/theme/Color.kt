package com.factoriasoftware.factorybrain.ui.theme

import androidx.compose.ui.graphics.Color

/**
 * Paleta fija de fallback de Factory Brain (T-FB017-US05-01).
 *
 * Elección del color semilla: no existe una guía de marca publicada, así
 * que se fija un color semilla propio — un verde azulado (teal) profundo,
 * `0xFF00696D`. Se eligió por la identidad del producto:
 *  - "Brain" -> la referencia técnica/neurológica; el teal transmite
 *    claridad, ciencia y calma, a la vez que es distinto de los "azules
 *    corporativos" genéricos.
 *  - Base oscura y saturada: funciona bien como `primary` tanto en claro
 *    como en oscuro sin chocar con el Dynamic Color de Android, del que
 *    este esquema es el fallback.
 *
 * La gama completa (light/dark) se deriva del semilla con la metodología
 * Material 3 (tonal palettes: 40/100 para primary, y los tonos de contraste
 * con background/surface). Idealmente se obtendría del Material Theme
 * Builder oficial; los valores de aquí son coherentes con esa metodología y
 * se marcan como candidatos a validar visualmente en dispositivo (ver
 * resumen de la Task).
 */

// Color semilla de identidad (documentación explícita de la elección).
val FabSeed = Color(0xFF006A6D)

// Light scheme
val FabPrimaryLight = Color(0xFF00696D)
val FabOnPrimaryLight = Color(0xFFFFFFFF)
val FabPrimaryContainerLight = Color(0xFF9CF1F4)
val FabOnPrimaryContainerLight = Color(0xFF002021)
val FabSecondaryLight = Color(0xFF4A6365)
val FabOnSecondaryLight = Color(0xFFFFFFFF)
val FabSecondaryContainerLight = Color(0xFFCCE8EA)
val FabOnSecondaryContainerLight = Color(0xFF051F21)
val FabTertiaryLight = Color(0xFF4B5C7D)
val FabOnTertiaryLight = Color(0xFFFFFFFF)
val FabTertiaryContainerLight = Color(0xFFD9E2FF)
val FabOnTertiaryContainerLight = Color(0xFF091A3F)
val FabBackgroundLight = Color(0xFFFAFDFD)
val FabOnBackgroundLight = Color(0xFF191C1C)
val FabSurfaceLight = Color(0xFFFAFDFD)
val FabOnSurfaceLight = Color(0xFF191C1C)
val FabSurfaceVariantLight = Color(0xFFDAE4E4)
val FabOnSurfaceVariantLight = Color(0xFF3F4949)
val FabOutlineLight = Color(0xFF6F7979)
val FabErrorLight = Color(0xFFBA1A1A)
val FabOnErrorLight = Color(0xFFFFFFFF)
val FabErrorContainerLight = Color(0xFFFFDAD6)
val FabOnErrorContainerLight = Color(0xFF410002)

// Dark scheme
val FabPrimaryDark = Color(0xFF80D4D7)
val FabOnPrimaryDark = Color(0xFF00373A)
val FabPrimaryContainerDark = Color(0xFF004F52)
val FabOnPrimaryContainerDark = Color(0xFF9CF1F4)
val FabSecondaryDark = Color(0xFFB0CCCE)
val FabOnSecondaryDark = Color(0xFF1B3436)
val FabSecondaryContainerDark = Color(0xFF324B4D)
val FabOnSecondaryContainerDark = Color(0xFFCCE8EA)
val FabTertiaryDark = Color(0xFFBAC6EB)
val FabOnTertiaryDark = Color(0xFF232F4C)
val FabTertiaryContainerDark = Color(0xFF3B4664)
val FabOnTertiaryContainerDark = Color(0xFFD9E2FF)
val FabBackgroundDark = Color(0xFF191C1C)
val FabOnBackgroundDark = Color(0xFFE0E3E3)
val FabSurfaceDark = Color(0xFF191C1C)
val FabOnSurfaceDark = Color(0xFFE0E3E3)
val FabSurfaceVariantDark = Color(0xFF3F4949)
val FabOnSurfaceVariantDark = Color(0xFFBEC8C8)
val FabOutlineDark = Color(0xFF899393)
val FabErrorDark = Color(0xFFFFB4AB)
val FabOnErrorDark = Color(0xFF690005)
val FabErrorContainerDark = Color(0xFF93000A)
val FabOnErrorContainerDark = Color(0xFFFFDAD6)