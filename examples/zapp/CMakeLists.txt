cmake_minimum_required(VERSION 4.0)
project(zapp CXX)

find_package(Freetype REQUIRED)
find_package(greetgen REQUIRED)

# greetgen is a tool: a program another recipe builds, which this build runs
set(greeting_header ${CMAKE_CURRENT_BINARY_DIR}/generated/greeting_text.h)
add_custom_command(OUTPUT ${greeting_header}
  COMMAND greetgen::greetgen ${greeting_header}
  DEPENDS greetgen::greetgen)

add_executable(zapp main.cpp greeting.cpp ${greeting_header})
target_include_directories(zapp PRIVATE ${CMAKE_CURRENT_BINARY_DIR}/generated)
target_link_libraries(zapp PRIVATE Freetype::Freetype)
install(TARGETS zapp RUNTIME DESTINATION bin)

# Put the DLLs of shared dependencies next to the executable. The list is empty when all are static.
set(runtime_dlls $<TARGET_RUNTIME_DLLS:zapp>)
add_custom_command(TARGET zapp POST_BUILD
  COMMAND "$<$<BOOL:${runtime_dlls}>:${CMAKE_COMMAND};-E;copy_if_different;${runtime_dlls};$<TARGET_FILE_DIR:zapp>>"
  COMMAND_EXPAND_LISTS)
