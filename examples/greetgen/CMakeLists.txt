cmake_minimum_required(VERSION 4.0)
project(greetgen CXX)

add_executable(greetgen main.cpp)
install(TARGETS greetgen RUNTIME DESTINATION bin)
