cmake_minimum_required(VERSION 4.0)
project(zapp CXX)

find_package(zlib CONFIG REQUIRED)

add_executable(zapp main.cpp greeting.cpp)
target_link_libraries(zapp PRIVATE zlib::zlib)
install(TARGETS zapp RUNTIME DESTINATION bin)
