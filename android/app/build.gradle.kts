plugins {
    id("com.android.application")
    // Kotlin support is built into AGP 9+: no kotlin.android plugin.
}

android {
    namespace = "ai.jarvis.node"
    // core-ktx 1.19.x requires compiling against API 37+; targetSdk
    // stays 34 to avoid opting into new runtime behavior.
    compileSdk = 37

    defaultConfig {
        applicationId = "ai.jarvis.node"
        minSdk = 26
        targetSdk = 34
        versionCode = 2
        // Must match the core-side ANDROID expectations (android.py).
        versionName = "3.10.0"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    // AGP 9 built-in Kotlin: jvmTarget defaults to targetCompatibility.
}

dependencies {
    implementation("androidx.core:core-ktx:1.19.1")
    implementation("androidx.appcompat:appcompat:1.8.0")
    testImplementation("junit:junit:4.13.2")
    // Real org.json for JVM unit tests: android.jar stubs throw
    // "not mocked" at runtime, so anything touching JSONObject needs this.
    testImplementation("org.json:json:20240303")
}
