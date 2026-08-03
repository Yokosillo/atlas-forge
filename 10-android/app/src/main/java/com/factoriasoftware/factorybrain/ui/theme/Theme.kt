package com.factoriasoftware.factorybrain.ui.theme

import android.os.Build
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.dynamicDarkColorScheme
import androidx.compose.material3.dynamicLightColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.platform.LocalContext

private val LightColors = lightColorScheme(
    primary = FabPrimaryLight,
    onPrimary = FabOnPrimaryLight,
    primaryContainer = FabPrimaryContainerLight,
    onPrimaryContainer = FabOnPrimaryContainerLight,
    secondary = FabSecondaryLight,
    onSecondary = FabOnSecondaryLight,
    secondaryContainer = FabSecondaryContainerLight,
    onSecondaryContainer = FabOnSecondaryContainerLight,
    tertiary = FabTertiaryLight,
    onTertiary = FabOnTertiaryLight,
    tertiaryContainer = FabTertiaryContainerLight,
    onTertiaryContainer = FabOnTertiaryContainerLight,
    background = FabBackgroundLight,
    onBackground = FabOnBackgroundLight,
    surface = FabSurfaceLight,
    onSurface = FabOnSurfaceLight,
    surfaceVariant = FabSurfaceVariantLight,
    onSurfaceVariant = FabOnSurfaceVariantLight,
    outline = FabOutlineLight,
    error = FabErrorLight,
    onError = FabOnErrorLight,
    errorContainer = FabErrorContainerLight,
    onErrorContainer = FabOnErrorContainerLight,
)

private val DarkColors = darkColorScheme(
    primary = FabPrimaryDark,
    onPrimary = FabOnPrimaryDark,
    primaryContainer = FabPrimaryContainerDark,
    onPrimaryContainer = FabOnPrimaryContainerDark,
    secondary = FabSecondaryDark,
    onSecondary = FabOnSecondaryDark,
    secondaryContainer = FabSecondaryContainerDark,
    onSecondaryContainer = FabOnSecondaryContainerDark,
    tertiary = FabTertiaryDark,
    onTertiary = FabOnTertiaryDark,
    tertiaryContainer = FabTertiaryContainerDark,
    onTertiaryContainer = FabOnTertiaryContainerDark,
    background = FabBackgroundDark,
    onBackground = FabOnBackgroundDark,
    surface = FabSurfaceDark,
    onSurface = FabOnSurfaceDark,
    surfaceVariant = FabSurfaceVariantDark,
    onSurfaceVariant = FabOnSurfaceVariantDark,
    outline = FabOutlineDark,
    error = FabErrorDark,
    onError = FabOnErrorDark,
    errorContainer = FabErrorContainerDark,
    onErrorContainer = FabOnErrorContainerDark,
)

/**
 * Tema Material 3 de Factory Brain (T-FB017-US05-01).
 *
 * Resolver el `colorScheme`:
 *  - Si `dynamicColor` es true Y el dispositivo es Android 12+ (API 31),
 *    se usa el Dynamic Color del sistema (`dynamicLightColorScheme` /
 *    `dynamicDarkColorScheme`), para que la app adopte los tonos
 *    personalizados del usuario.
 *  - Si no, se usa el esquema fijo de `Color.kt` (light o dark según
 *    `darkTheme`), el fallback de identidad propio (API < 31 o dynamic
 *    desactivado).
 *
 * `darkTheme` y `dynamicColor` son parámetros con default para que el resto
 * de la app no tenga que preocuparse por ellos (seguimiento automático del
 * sistema por defecto), pero sin perder la posibilidad de forzarlos en
 * test/preview.
 */
@Composable
fun FactoryBrainTheme(
    darkTheme: Boolean = isSystemInDarkTheme(),
    dynamicColor: Boolean = true,
    content: @Composable () -> Unit,
) {
    val context = LocalContext.current
    val colorScheme = when {
        dynamicColor && Build.VERSION.SDK_INT >= Build.VERSION_CODES.S -> {
            if (darkTheme) dynamicDarkColorScheme(context) else dynamicLightColorScheme(context)
        }
        darkTheme -> DarkColors
        else -> LightColors
    }

    MaterialTheme(
        colorScheme = colorScheme,
        typography = Typography,
        content = content,
    )
}