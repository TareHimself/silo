cmake_minimum_required(VERSION 4.0)
project(webm CXX)

find_package(webmdx REQUIRED)

add_executable(webm main.cpp)
target_link_libraries(webm PRIVATE webmdx::webmdx)

install(TARGETS webm RUNTIME DESTINATION bin)
install(FILES $<TARGET_RUNTIME_DLLS:webm> DESTINATION bin)
