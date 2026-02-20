# SPDX-License-Identifier: Apache-2.0
# Zephlet code generation CMake module
# Auto-generates zephlet infrastructure (.h, .c, private/*_priv.h) during build

function(zephyr_zephlet_generate ZEPHLET_NAME PROTO_FILE)
  set(CODEGEN_SCRIPT "${ZEPHYR_SHARED_ZEPHLET_MODULE_DIR}/codegen/generate_zephlet.py")
  set(OUTPUT_DIR "${CMAKE_CURRENT_BINARY_DIR}")

  set(GENERATED_H "${OUTPUT_DIR}/${ZEPHLET_NAME}_interface.h")
  set(GENERATED_C "${OUTPUT_DIR}/${ZEPHLET_NAME}_interface.c")
  set(GENERATED_PRIV_H "${OUTPUT_DIR}/${ZEPHLET_NAME}.h")

  file(GLOB TEMPLATE_FILES "${ZEPHYR_SHARED_ZEPHLET_MODULE_DIR}/codegen/templates/*.jinja")

  # Check if .c exists in source, generate once if missing (bootstrap)
  set(IMPL_FILE "${CMAKE_CURRENT_SOURCE_DIR}/${ZEPHLET_NAME}.c")
  if(NOT EXISTS ${IMPL_FILE})
    message(STATUS "Bootstrapping ${ZEPHLET_NAME}.c (one-time generation)")
    execute_process(
      COMMAND ${PYTHON_EXECUTABLE} ${CODEGEN_SCRIPT}
        --proto ${PROTO_FILE}
        --output-dir ${CMAKE_CURRENT_SOURCE_DIR}
        --zephlet-name ${ZEPHLET_NAME}
        --module-dir ${CMAKE_CURRENT_SOURCE_DIR}
        --impl-only
      WORKING_DIRECTORY ${CMAKE_SOURCE_DIR}
      RESULT_VARIABLE BOOTSTRAP_RESULT
    )
    if(NOT BOOTSTRAP_RESULT EQUAL 0)
      message(FATAL_ERROR "Failed to bootstrap ${ZEPHLET_NAME}.c")
    endif()
  endif()

  # Auto-generate infrastructure files to build directory
  add_custom_command(
    OUTPUT ${GENERATED_H} ${GENERATED_C} ${GENERATED_PRIV_H}
    COMMAND ${PYTHON_EXECUTABLE} ${CODEGEN_SCRIPT}
      --proto ${PROTO_FILE}
      --output-dir ${OUTPUT_DIR}
      --zephlet-name ${ZEPHLET_NAME}
      --module-dir ${CMAKE_CURRENT_SOURCE_DIR}
      --no-generate-impl
    DEPENDS ${PROTO_FILE} ${TEMPLATE_FILES} ${CODEGEN_SCRIPT}
    COMMENT "Generating ${ZEPHLET_NAME} from ${PROTO_FILE}"
    VERBATIM
  )

  add_custom_target(${ZEPHLET_NAME}_codegen
    DEPENDS ${GENERATED_H} ${GENERATED_C} ${GENERATED_PRIV_H})

  set(${ZEPHLET_NAME}_GENERATED_C ${GENERATED_C} PARENT_SCOPE)
endfunction()

# Helper: capitalize first letter of a string (tick -> Tick)
function(_zephlet_capitalize INPUT OUTPUT_VAR)
  string(SUBSTRING "${INPUT}" 0 1 _first)
  string(TOUPPER "${_first}" _first)
  string(SUBSTRING "${INPUT}" 1 -1 _rest)
  set(${OUTPUT_VAR} "${_first}${_rest}" PARENT_SCOPE)
endfunction()

# Adapter code generation
# Generates auto-gen adapter.c (build dir) and bootstraps _impl.c (source dir)
# Handles Kconfig guard, zephyr_library_sources, and add_dependencies internally.
#
# Usage:
#   zephlet_adapter_generate(ORIGIN tick DEST ui REPORTS events)
#
# Derives CONFIG_<ORIGIN>_TO_<DEST>_ADAPTER and skips if disabled.
# Requires ZEPHLETS_PATH to be set in caller scope.
function(zephlet_adapter_generate)
  cmake_parse_arguments(ARG "" "ORIGIN;DEST" "REPORTS" ${ARGN})

  if(NOT ARG_ORIGIN OR NOT ARG_DEST OR NOT ARG_REPORTS)
    message(FATAL_ERROR "zephlet_adapter_generate: ORIGIN, DEST, and REPORTS are required")
  endif()

  if(NOT ZEPHLETS_PATH)
    message(FATAL_ERROR "zephlet_adapter_generate: ZEPHLETS_PATH must be set")
  endif()

  # Derive Kconfig symbol: CONFIG_TICK_TO_UI_ADAPTER
  string(TOUPPER "${ARG_ORIGIN}" _origin_upper)
  string(TOUPPER "${ARG_DEST}" _dest_upper)
  set(_config_var "CONFIG_${_origin_upper}_TO_${_dest_upper}_ADAPTER")

  if(NOT ${_config_var})
    return()
  endif()

  # Derive adapter name: Tick+Ui_zlet_adapter
  _zephlet_capitalize(${ARG_ORIGIN} _origin_cap)
  _zephlet_capitalize(${ARG_DEST} _dest_cap)
  set(ADAPTER_NAME "${_origin_cap}+${_dest_cap}_zlet_adapter")

  # Join REPORTS list into comma-separated string for --fields
  list(JOIN ARG_REPORTS "," SELECTED_FIELDS)

  set(CODEGEN_SCRIPT "${ZEPHYR_SHARED_ZEPHLET_MODULE_DIR}/codegen/generate_adapter.py")
  set(BUILD_OUTPUT "${CMAKE_CURRENT_BINARY_DIR}/${ADAPTER_NAME}.c")
  set(IMPL_FILE "${CMAKE_CURRENT_SOURCE_DIR}/src/${ADAPTER_NAME}_impl.c")

  file(GLOB TEMPLATE_FILES "${ZEPHYR_SHARED_ZEPHLET_MODULE_DIR}/codegen/templates/adapter*.jinja")
  file(GLOB PROTO_FILES "${ZEPHLETS_PATH}/*/*.proto")

  # Bootstrap: generate _impl.c if missing
  if(NOT EXISTS ${IMPL_FILE})
    message(STATUS "Bootstrapping ${ADAPTER_NAME}_impl.c (one-time generation)")
    execute_process(
      COMMAND ${PYTHON_EXECUTABLE} ${CODEGEN_SCRIPT}
        --non-interactive
        --zephlets-path ${ZEPHLETS_PATH}
        --origin ${ARG_ORIGIN}
        --dest ${ARG_DEST}
        --fields "${SELECTED_FIELDS}"
        --output-dir ${CMAKE_CURRENT_SOURCE_DIR}
        --impl-only
      WORKING_DIRECTORY ${CMAKE_SOURCE_DIR}
      RESULT_VARIABLE BOOTSTRAP_RESULT
    )
    if(NOT BOOTSTRAP_RESULT EQUAL 0)
      message(FATAL_ERROR "Failed to bootstrap ${ADAPTER_NAME}_impl.c")
    endif()
  endif()

  # Build-time: always re-gen adapter.c to build dir + smart-update impl
  add_custom_command(
    OUTPUT ${BUILD_OUTPUT}
    COMMAND ${PYTHON_EXECUTABLE} ${CODEGEN_SCRIPT}
      --non-interactive
      --zephlets-path ${ZEPHLETS_PATH}
      --origin ${ARG_ORIGIN}
      --dest ${ARG_DEST}
      --fields "${SELECTED_FIELDS}"
      --output-dir ${CMAKE_CURRENT_SOURCE_DIR}
      --build-dir ${CMAKE_CURRENT_BINARY_DIR}
    DEPENDS ${PROTO_FILES} ${TEMPLATE_FILES} ${CODEGEN_SCRIPT}
    COMMENT "Generating ${ADAPTER_NAME} adapter"
    VERBATIM
  )

  add_custom_target(${ADAPTER_NAME}_codegen DEPENDS ${BUILD_OUTPUT})

  zephyr_library_sources(${BUILD_OUTPUT} "src/${ADAPTER_NAME}_impl.c")
  add_dependencies(${ZEPHYR_CURRENT_LIBRARY} ${ADAPTER_NAME}_codegen)
endfunction()
