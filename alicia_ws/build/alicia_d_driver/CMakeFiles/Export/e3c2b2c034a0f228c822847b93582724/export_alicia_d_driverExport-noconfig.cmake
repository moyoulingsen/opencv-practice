#----------------------------------------------------------------
# Generated CMake target import file.
#----------------------------------------------------------------

# Commands may need to know the format version.
set(CMAKE_IMPORT_FILE_VERSION 1)

# Import target "alicia_d_driver::alicia_d_hardware_interface" for configuration ""
set_property(TARGET alicia_d_driver::alicia_d_hardware_interface APPEND PROPERTY IMPORTED_CONFIGURATIONS NOCONFIG)
set_target_properties(alicia_d_driver::alicia_d_hardware_interface PROPERTIES
  IMPORTED_LOCATION_NOCONFIG "${_IMPORT_PREFIX}/lib/libalicia_d_hardware_interface.so"
  IMPORTED_SONAME_NOCONFIG "libalicia_d_hardware_interface.so"
  )

list(APPEND _cmake_import_check_targets alicia_d_driver::alicia_d_hardware_interface )
list(APPEND _cmake_import_check_files_for_alicia_d_driver::alicia_d_hardware_interface "${_IMPORT_PREFIX}/lib/libalicia_d_hardware_interface.so" )

# Import target "alicia_d_driver::serial_communicator_lib" for configuration ""
set_property(TARGET alicia_d_driver::serial_communicator_lib APPEND PROPERTY IMPORTED_CONFIGURATIONS NOCONFIG)
set_target_properties(alicia_d_driver::serial_communicator_lib PROPERTIES
  IMPORTED_LOCATION_NOCONFIG "${_IMPORT_PREFIX}/lib/libserial_communicator_lib.so"
  IMPORTED_SONAME_NOCONFIG "libserial_communicator_lib.so"
  )

list(APPEND _cmake_import_check_targets alicia_d_driver::serial_communicator_lib )
list(APPEND _cmake_import_check_files_for_alicia_d_driver::serial_communicator_lib "${_IMPORT_PREFIX}/lib/libserial_communicator_lib.so" )

# Import target "alicia_d_driver::alicia_d_data_parser_control_lib" for configuration ""
set_property(TARGET alicia_d_driver::alicia_d_data_parser_control_lib APPEND PROPERTY IMPORTED_CONFIGURATIONS NOCONFIG)
set_target_properties(alicia_d_driver::alicia_d_data_parser_control_lib PROPERTIES
  IMPORTED_LOCATION_NOCONFIG "${_IMPORT_PREFIX}/lib/libalicia_d_data_parser_control_lib.so"
  IMPORTED_SONAME_NOCONFIG "libalicia_d_data_parser_control_lib.so"
  )

list(APPEND _cmake_import_check_targets alicia_d_driver::alicia_d_data_parser_control_lib )
list(APPEND _cmake_import_check_files_for_alicia_d_driver::alicia_d_data_parser_control_lib "${_IMPORT_PREFIX}/lib/libalicia_d_data_parser_control_lib.so" )

# Commands beyond this point should not need to know the version.
set(CMAKE_IMPORT_FILE_VERSION)
