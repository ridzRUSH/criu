#!/usr/bin/env python3
#
#  monti_carlo.py
#  
#  Copyright 2026 vm2 <vm2@vm2>
#  
#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 2 of the License, or
#  (at your option) any later version.
#  
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#  
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software
#  Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
#  MA 02110-1301, USA.
#  
#  

import sys
import random


def monti_carlo_pi(iterations):

    inside_circle = 0
    total_points = 0

    for i in range(iterations):

        derived_x = random.random() * 2 - 1
        derived_y = random.random() * 2 - 1

        dist_from_origin = derived_x**2 + derived_y**2

        if dist_from_origin <= 1:
            inside_circle += 1

        total_points += 1

        pi = 4 * inside_circle / total_points

        print(f"At iteration {i} pi is {pi}")


    print("\n-- FINAL PI CALCULATION --")

    final_pi = 4 * inside_circle / total_points

    print(f"Pi is {final_pi}")



def main(args):

    monti_carlo_pi(10**12)

    return 0



if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
