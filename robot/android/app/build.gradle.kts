plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.jepa.recorder"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.jepa.recorder"
        minSdk = 26
        targetSdk = 34
        versionCode = 4
        versionName = "0.4-safe"
    }
    buildTypes {
        release { isMinifyEnabled = false }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
    buildFeatures { viewBinding = true }
}

dependencies {
    val camerax = "1.3.4"
    implementation("androidx.camera:camera-core:$camerax")
    implementation("androidx.camera:camera-camera2:$camerax")          // Camera2 interop (chọn ultrawide)
    implementation("androidx.camera:camera-lifecycle:$camerax")
    implementation("androidx.camera:camera-view:$camerax")
    implementation("com.github.mik3y:usb-serial-for-android:3.7.0")     // USB-serial NO-ROOT
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.8.4")
    implementation("com.google.android.material:material:1.12.0")
    implementation("androidx.recyclerview:recyclerview:1.3.2")          // danh sách session
    implementation("com.google.android.gms:play-services-auth:21.2.0")  // Google Sign-In (Drive)
    implementation("com.squareup.okhttp3:okhttp:4.12.0")                // gọi REST Drive (resumable upload)
}
