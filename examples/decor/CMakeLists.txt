cmake_minimum_required(VERSION 4.0)
project(decor C)

find_package(libdecor REQUIRED)
find_package(wayland REQUIRED)

add_executable(decor main.c)
target_link_libraries(decor PRIVATE libdecor::libdecor wayland::wayland-client)
install(TARGETS decor RUNTIME DESTINATION bin)
install(FILES ${SILO_RUNTIME_LIBRARIES} DESTINATION bin)
