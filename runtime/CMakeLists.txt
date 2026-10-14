cmake_minimum_required(VERSION 3.20)

# Runtime: compiles the N64Recomp output (../RecompiledFuncs) and links it with N64ModernRuntime
# (ultramodern + librecomp), RT64 (graphics) and RecompFrontend (launcher, settings menus, SDL input).
# Build with clang-cl + Ninja from a VS developer environment: see build.ps1.

project(SomesayRecomp LANGUAGES C CXX)
set(CMAKE_C_STANDARD 17)
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

if (CMAKE_CXX_COMPILER_ID STREQUAL "Clang" AND CMAKE_CXX_SIMULATE_ID STREQUAL "MSVC")
    set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -Wno-everything /W4")
    # Source paths end up in the exe: make them relative to the project root so a shared exe doesn't show build machine paths.
    get_filename_component(SOMESAY_SOURCE_ROOT "${CMAKE_SOURCE_DIR}/.." ABSOLUTE)
    file(TO_NATIVE_PATH "${SOMESAY_SOURCE_ROOT}" SOMESAY_SOURCE_ROOT_NATIVE)
    set(SOMESAY_PREFIX_MAP "/clang:-ffile-prefix-map=${SOMESAY_SOURCE_ROOT}/= /clang:-ffile-prefix-map=${SOMESAY_SOURCE_ROOT_NATIVE}\\=")
    set(CMAKE_C_FLAGS "${CMAKE_C_FLAGS} ${SOMESAY_PREFIX_MAP}")
    set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} ${SOMESAY_PREFIX_MAP}")
endif()

# The C/C++ runtime goes into somesay.exe (/MT) for every target.
set(CMAKE_MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>")

# Avoid vcredist issues with the constexpr mutex constructor
add_compile_definitions(_DISABLE_CONSTEXPR_MUTEX_CONSTRUCTOR)

if (CMAKE_VERSION VERSION_GREATER_EQUAL "3.24.0")
    cmake_policy(SET CMP0135 NEW)
endif()

set(CMAKE_RUNTIME_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR})
set(BUILD_SHARED_LIBS OFF)

# N64ModernRuntime lives in tools/ (pinned checkout).
set(N64MODERNRUNTIME_DIR "${CMAKE_SOURCE_DIR}/../tools/N64ModernRuntime" CACHE PATH "N64ModernRuntime checkout")
add_subdirectory(${N64MODERNRUNTIME_DIR} ${CMAKE_BINARY_DIR}/N64ModernRuntime)

# RT64 renderer in tools/ (pinned checkout).
set(RT64_DIR "${CMAKE_SOURCE_DIR}/../tools/rt64" CACHE PATH "RT64 checkout")
set(RT64_STATIC TRUE)
add_compile_definitions(HLSL_CPU NOMINMAX)
add_subdirectory(${RT64_DIR} ${CMAKE_BINARY_DIR}/rt64)
target_include_directories(rt64 PRIVATE ${CMAKE_BINARY_DIR}/rt64/src)
# RT64's bundled SDL 2.26.3 defines _m_prefetch by hand (old-clang workaround), newer clang rejects it.
add_compile_definitions(__PRFCHWINTRIN_H)
# Newer clang makes this an error; imgui passes an uninitialized char with length 0.
target_compile_options(rt64 PRIVATE -Wno-uninitialized-const-pointer)

# SDL2 2.30.3: window, input and audio.
include(FetchContent)
FetchContent_Declare(sdl2
    URL https://github.com/libsdl-org/SDL/releases/download/release-2.30.3/SDL2-devel-2.30.3-VC.zip)
FetchContent_MakeAvailable(sdl2)

# Shader compiler settings for RT64's build_*_shader functions (as Banjo: Recompiled).
set(DXC "${RT64_DIR}/src/contrib/dxc/bin/x64/dxc.exe")
set(DXC_COMMON_OPTS "-I${PROJECT_SOURCE_DIR}/src")
set(DXC_DXIL_OPTS "-Wno-ignored-attributes")
set(DXC_SPV_OPTS "-spirv" "-fspv-target-env=vulkan1.0" "-fvk-use-dx-layout")
set(DXC_PS_OPTS "${DXC_COMMON_OPTS}" "-E" "PSMain" "-T ps_6_0" "-D DYNAMIC_RENDER_PARAMS")
set(DXC_VS_OPTS "${DXC_COMMON_OPTS}" "-E" "VSMain" "-T vs_6_0" "-D DYNAMIC_RENDER_PARAMS" "-fvk-invert-y")
set(DXC_CS_OPTS "${DXC_COMMON_OPTS}" "-E" "CSMain" "-T cs_6_0")
set(DXC_GS_OPTS "${DXC_COMMON_OPTS}" "-E" "GSMain" "-T gs_6_0")
set(DXC_RT_OPTS "${DXC_COMMON_OPTS}" "-D" "RT_SHADER" "-T" "lib_6_3" "-fspv-target-env=vulkan1.1spirv1.4" "-fspv-extension=SPV_KHR_ray_tracing" "-fspv-extension=SPV_EXT_descriptor_indexing")

# RecompFrontend in tools/.
set(RECOMPFRONTEND_DIR "${CMAKE_SOURCE_DIR}/../tools/RecompFrontend" CACHE PATH "RecompFrontend checkout")
set(RECOMP_FRONTEND_N64MODERNRUNTIME_PATH ${N64MODERNRUNTIME_DIR})
set(RECOMP_FRONTEND_RT64_PATH ${RT64_DIR})
add_subdirectory(${RECOMPFRONTEND_DIR} ${CMAKE_BINARY_DIR}/RecompFrontend)
# runtime\include\ui_funcs.h: stand-in for a game header recompui expects.
target_include_directories(recompui PRIVATE ${CMAKE_SOURCE_DIR}/include)

set(RECOMPILED_DIR "${CMAKE_SOURCE_DIR}/../RecompiledFuncs")

option(SOMESAY_LIVE "Build the live shell (game code recompiled from the ROM at startup)" OFF)

if (NOT SOMESAY_LIVE)
# RecompiledFuncs - the N64Recomp output (generated, not in git)
add_library(RecompiledFuncs STATIC)

target_compile_options(RecompiledFuncs PRIVATE
    -fno-strict-aliasing
    -Wno-unused-variable
    -Wno-implicit-function-declaration
    -Wno-everything
)

target_include_directories(RecompiledFuncs PRIVATE
    ${N64MODERNRUNTIME_DIR}/ultramodern/include
    ${N64MODERNRUNTIME_DIR}/librecomp/include
    ${N64MODERNRUNTIME_DIR}/N64Recomp/include
)

file(GLOB FUNC_C_SOURCES ${RECOMPILED_DIR}/*.c)
file(GLOB FUNC_CXX_SOURCES ${RECOMPILED_DIR}/*.cpp)
target_sources(RecompiledFuncs PRIVATE ${FUNC_C_SOURCES} ${FUNC_CXX_SOURCES})
endif()

# Main executable (Phase 5: minimal — main.cpp, input.cpp, audio.cpp, config.cpp).
# embedded_files_unpack.cpp + generated embedded_files.cpp embed runtime/assets/ into the exe.

add_executable(somesay src/main.cpp src/input.cpp src/audio.cpp src/config.cpp
    src/embedded_files_unpack.cpp ${CMAKE_BINARY_DIR}/embedded_files.cpp)

# Version shown in the launcher = package\\VERSION.
set(CMAKE_CONFIGURE_DEPENDS "${CMAKE_SOURCE_DIR}/package/VERSION")
file(STRINGS "${CMAKE_SOURCE_DIR}/package/VERSION" SOMESAY_VERSION LIMIT_COUNT 1)
string(STRIP "${SOMESAY_VERSION}" SOMESAY_VERSION)
if (NOT SOMESAY_VERSION MATCHES "^([0-9]+)\\.([0-9]+)\\.([0-9]+)$")
    message(FATAL_ERROR "package/VERSION must be like 1.2.3, is '${SOMESAY_VERSION}'")
endif()
target_compile_definitions(somesay PRIVATE SOMESAY_VERSION_MAJOR=${CMAKE_MATCH_1} SOMESAY_VERSION_MINOR=${CMAKE_MATCH_2}
    SOMESAY_VERSION_PATCH=${CMAKE_MATCH_3})

# Asset files built into somesay.exe (generated by CMakeLists.txt into build/ embedded_files.cpp): fonts, SVG icons and UI CSS.
# unpack_embedded_files writes them into data\ at startup so the runtime loads them from disk.
file(GLOB_RECURSE SOMESAY_ASSET_FILES CONFIGURE_DEPENDS RELATIVE "${CMAKE_SOURCE_DIR}" "${CMAKE_SOURCE_DIR}/assets/*")
set(SOMESAY_EMBEDDED "")
foreach (file ${SOMESAY_ASSET_FILES})
    list(APPEND SOMESAY_EMBEDDED "${file}|${CMAKE_SOURCE_DIR}/${file}|1")
endforeach()
set(SOMESAY_EMBED_ARRAYS "")
set(SOMESAY_EMBED_ENTRIES "")
set(SOMESAY_EMBED_SOURCES "")
math(EXPR somesay_embed_index "0")
foreach (entry ${SOMESAY_EMBEDDED})
    string(REPLACE "|" ";" parts "${entry}")
    list(GET parts 0 published)
    list(GET parts 1 source)
    list(GET parts 2 unpack)
    get_filename_component(source "${source}" ABSOLUTE)
    if (unpack)
        set(unpack true)
    else()
        set(unpack false)
    endif()
    string(APPEND SOMESAY_EMBED_ARRAYS "static const unsigned char file${somesay_embed_index}[] = {\n#embed \"${source}\" suffix(,)\n0 };\n")
    string(APPEND SOMESAY_EMBED_ENTRIES "    { \"${published}\", file${somesay_embed_index}, sizeof(file${somesay_embed_index}) - 1, ${unpack} },\n")
    list(APPEND SOMESAY_EMBED_SOURCES "${source}")
    math(EXPR somesay_embed_index "${somesay_embed_index} + 1")
endforeach()
file(CONFIGURE OUTPUT "${CMAKE_BINARY_DIR}/embedded_files.cpp" @ONLY CONTENT
"// Generated by runtime/CMakeLists.txt: the files built into somesay.exe (see src/embedded_files.h).
#include \"embedded_files.h\"

${SOMESAY_EMBED_ARRAYS}namespace somesay {
const EmbeddedFile embedded_files[] = {
${SOMESAY_EMBED_ENTRIES}};
const size_t embedded_file_count = ${somesay_embed_index};
}
")
set_source_files_properties(${CMAKE_BINARY_DIR}/embedded_files.cpp PROPERTIES
    OBJECT_DEPENDS "${SOMESAY_EMBED_SOURCES}" COMPILE_OPTIONS "-Wno-c23-extensions")

target_include_directories(somesay PRIVATE ${CMAKE_SOURCE_DIR}/src)
target_include_directories(somesay PRIVATE ${RECOMPILED_DIR}) # recomp_overlays.inl

target_include_directories(somesay PRIVATE
    ${sdl2_SOURCE_DIR}/include
    ${N64MODERNRUNTIME_DIR}/ultramodern/include
    ${N64MODERNRUNTIME_DIR}/N64Recomp/include
    ${RT64_DIR}/src
    ${RT64_DIR}/src/contrib
    ${RT64_DIR}/src/contrib/hlslpp/include
    ${RT64_DIR}/src/contrib/dxc/inc
    ${RT64_DIR}/src/rhi
    ${RT64_DIR}/src/render
    ${RT64_DIR}/src/contrib/nativefiledialog-extended/src/include
    ${RECOMPFRONTEND_DIR}/recompinput/include
    ${RECOMPFRONTEND_DIR}/recompui/include
    ${RECOMPFRONTEND_DIR}/recompui/src
)
target_link_directories(somesay PRIVATE ${sdl2_SOURCE_DIR}/lib/x64)

# -march=nehalem: the recompiled RSP vector code needs SSE4.1 (needed later for audio microcode).
target_compile_options(somesay PRIVATE -march=nehalem -fno-strict-aliasing -fms-extensions)

if (MSVC)
    # Identical code folding breaks function patching
    target_link_options(somesay PRIVATE /OPT:NOICF)
    # Only the .pdb's file name in the exe, not the build folder.
    target_link_options(somesay PRIVATE "/PDBALTPATH:%_PDB%")
endif()

# RecompiledFuncs must come first: it and librecomp both define 64-bit division helpers.
if (NOT SOMESAY_LIVE)
    target_link_libraries(somesay PRIVATE RecompiledFuncs)
endif()
target_link_libraries(somesay PRIVATE recompui recompinput librecomp ultramodern rt64 nfd SDL2 Winmm.lib)

# Next to the exe: SDL2.dll and RT64's shader compiler DLLs.
add_custom_command(TARGET somesay POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy_if_different
        "${sdl2_SOURCE_DIR}/lib/x64/SDL2.dll"
        "${RT64_DIR}/src/contrib/dxc/bin/x64/dxil.dll"
        "${RT64_DIR}/src/contrib/dxc/bin/x64/dxcompiler.dll"
        $<TARGET_FILE_DIR:somesay>)
