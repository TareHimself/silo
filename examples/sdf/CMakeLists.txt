cmake_minimum_required(VERSION 4.0)
project(sdf CXX)

find_package(msdfgen REQUIRED)

add_executable(sdf main.cpp)
target_link_libraries(sdf PRIVATE msdfgen::msdfgen)
install(TARGETS sdf RUNTIME DESTINATION bin)
