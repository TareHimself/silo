cmake_minimum_required(VERSION 4.0)
project(vpx CXX)

find_package(libvpx REQUIRED)

add_executable(vpx main.cpp)
target_link_libraries(vpx PRIVATE libvpx::libvpx)
install(TARGETS vpx RUNTIME DESTINATION bin)
