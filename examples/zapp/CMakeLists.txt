cmake_minimum_required(VERSION 4.0)
project(zapp CXX)

find_package(Freetype REQUIRED)

add_executable(zapp main.cpp greeting.cpp)
target_link_libraries(zapp PRIVATE Freetype::Freetype)
install(TARGETS zapp RUNTIME DESTINATION bin)
