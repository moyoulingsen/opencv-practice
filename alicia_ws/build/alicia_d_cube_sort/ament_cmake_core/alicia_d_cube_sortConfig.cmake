# generated from ament/cmake/core/templates/nameConfig.cmake.in

# prevent multiple inclusion
if(_alicia_d_cube_sort_CONFIG_INCLUDED)
  # ensure to keep the found flag the same
  if(NOT DEFINED alicia_d_cube_sort_FOUND)
    # explicitly set it to FALSE, otherwise CMake will set it to TRUE
    set(alicia_d_cube_sort_FOUND FALSE)
  elseif(NOT alicia_d_cube_sort_FOUND)
    # use separate condition to avoid uninitialized variable warning
    set(alicia_d_cube_sort_FOUND FALSE)
  endif()
  return()
endif()
set(_alicia_d_cube_sort_CONFIG_INCLUDED TRUE)

# output package information
if(NOT alicia_d_cube_sort_FIND_QUIETLY)
  message(STATUS "Found alicia_d_cube_sort: 1.0.0 (${alicia_d_cube_sort_DIR})")
endif()

# warn when using a deprecated package
if(NOT "" STREQUAL "")
  set(_msg "Package 'alicia_d_cube_sort' is deprecated")
  # append custom deprecation text if available
  if(NOT "" STREQUAL "TRUE")
    set(_msg "${_msg} ()")
  endif()
  # optionally quiet the deprecation message
  if(NOT alicia_d_cube_sort_DEPRECATED_QUIET)
    message(DEPRECATION "${_msg}")
  endif()
endif()

# flag package as ament-based to distinguish it after being find_package()-ed
set(alicia_d_cube_sort_FOUND_AMENT_PACKAGE TRUE)

# include all config extra files
set(_extras "")
foreach(_extra ${_extras})
  include("${alicia_d_cube_sort_DIR}/${_extra}")
endforeach()
