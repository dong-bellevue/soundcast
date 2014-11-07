import array as _array
import os
import shutil
import json
import csv
import pandas as pd
import h5py
import numpy as np
from input_configuration import *
from EmmeProject import *

def json_to_dictionary(dict_name):
    ''' Load supplemental input files as dictionary '''
    input_filename = os.path.join('inputs/supplemental/',dict_name+'.json').replace("\\","/")
    my_dictionary = json.load(open(input_filename))

    return(my_dictionary)

# Load the trip productions and attractions
trip_table = pd.read_csv(trip_table_loc, index_col="index")  # total 4K Ps and As by trip purpose
gq_trip_table = pd.read_csv(gq_trips_loc, index_col="index")  # only group quarter Ps and As

# Import JSON inputs as dictionaries
coeff = json_to_dictionary('gravity_model')
mode_dict = json_to_dictionary('mode_dict')
time_dict = json_to_dictionary('time_dict')
purp_tod_dict = json_to_dictionary('purp_tod_dict')
mode_list = ['svtl2', 'h2tl2', 'h3tl2', 'trnst', 'walk', 'bike']
time_periods = time_dict['svtl'].keys()

# Trip purposes lists - group quarters trips are only given for home-based inc class 1 (hw1)
trip_purp_full = ["hsp", "hbo", "sch", "wko", "col", "oto", "hw1", "hw2", "hw3", "hw4"]
trip_purp_gq = ["hsp", "hbo", "sch", "wko", "col", "oto", "hw1"]

def init_dir(directory):
    if os.path.exists(directory):
        shutil.rmtree(directory)
    os.mkdir(directory)

def network_importer(EmmeProject):
    for scenario in list(EmmeProject.bank.scenarios()):
            my_project.bank.delete_scenario(scenario)
        #create scenario
    EmmeProject.bank.create_scenario(1002)
    EmmeProject.change_scenario()
        #print key
    EmmeProject.delete_links()
    EmmeProject.delete_nodes()
    EmmeProject.process_modes('inputs/networks/' + mode_file)
    EmmeProject.process_base_network('inputs/networks/' + truck_base_net_name)  

def load_skims(skim_file_loc, mode_name, divide_by_100=False):
    ''' Loads H5 skim matrix for specified mode. '''
    with h5py.File(skim_file_loc, "r") as f:
        skim_file = f['Skims'][mode_name][:]
    # Divide by 100 since decimals were removed in H5 source file through multiplication
    if divide_by_100:
        return skim_file.astype(float)/100
    else:
        return skim_file

def calc_fric_fac(cost_skim, dist_skim):
    ''' Calculate friction factors for all trip purposes '''
    friction_fac_dic = {}
    # Need to fix this magic number
    magic_num = 33 # deal with holes in Emme matrices by subtracting this from numpy index
    for purpose, coeff_val in coeff.iteritems():
        friction_fac_dic[purpose] = np.exp((coeff[purpose])*(cost_skim + (dist_skim * autoop * avotda)))
        ## Set external zones to zero to prevent external-external trips
        friction_fac_dic[purpose][HIGH_STATION-magic_num:] = 0
        friction_fac_dic[purpose][:,[x for x in range(HIGH_STATION-magic_num, len(cost_skim))]] = 0

    return friction_fac_dic

def delete_matrices(my_project, matrix_type):
    ''' Deletes all Emme matrices of specified type in emmebank '''
    for matrix in my_project.bank.matrices():
        if matrix.type == matrix_type:
            my_project.delete_matrix(matrix)

def load_matrices_to_emme(trip_table_in, trip_purps, fric_facs, my_project):
    ''' Loads data to Emme matrices: Ps and As and friction factor by trip purpose.
        Also initializes empty trip distribution and O-D result tables. '''

    # list of matrix names
    matrix_name_list = [matrix.name for matrix in my_project.bank.matrices()]
    zonesDim = len(my_project.current_scenario.zone_numbers)
    zones = my_project.current_scenario.zone_numbers

    # Create Emme matrices if they don't already exist
    for purpose in trip_purps:
        print purpose
        if purpose + 'pro' not in matrix_name_list:
            my_project.create_matrix(str(purpose)+ "pro" , str(purpose) + " productions", "ORIGIN")
        if purpose + 'att' not in matrix_name_list:
            my_project.create_matrix(str(purpose) + "att", str(purpose) + " attractions", "DESTINATION")
        if purpose + 'fri' not in matrix_name_list:
            my_project.create_matrix(str(purpose) + "fri" , str(purpose) + "friction factors", "FULL")
        if purpose + 'dis' not in matrix_name_list:
            my_project.create_matrix(str(purpose) + "dis" , str(purpose) + "distributed trips", "FULL")
        if purpose + 'od' not in matrix_name_list:
            my_project.create_matrix(str(purpose) + "od" , str(purpose) + "O-D tables", "FULL")

        for p_a in ['pro', 'att']:
            # Load zonal production and attractions from CSV (output from trip generation)
            trips = np.array(trip_table_in[purpose + p_a])
            trips.resize(zonesDim)
            #code below does not work for GQs because there are only 3700 records in the csv file. Not sure if code above is ideal.
            #trips = np.array(trip_table_in.loc[0:zonesDim - 1][purpose + p_a])    # Less 1 because NumPy is 0-based\
            matrix_id = my_project.bank.matrix(purpose + p_a).id    
            emme_matrix = my_project.bank.matrix(matrix_id)  
            emme_matrix = ematrix.MatrixData(indices=[zones],type='f')    # Access Matrix API

             # Update Emme matrix data
            emme_matrix.raw_data = _array.array('f', trips)    # set raw matrix data equal to prod/attr data
            my_project.bank.matrix(matrix_id).set_data(emme_matrix, my_project.current_scenario)

        # Load friction factors by trip purpose
        fri_fac = fric_facs[purpose][0:zonesDim,0:zonesDim]
        emme_matrix = ematrix.MatrixData(indices=[zones,zones],type='f')    # Access Matrix API
        emme_matrix.raw_data = [_array.array('f',row) for row in fri_fac]
        matrix_id = my_project.bank.matrix(purpose + "fri").id    
        my_project.bank.matrix(matrix_id).set_data(emme_matrix, my_project.current_scenario)
                  
def balance_matrices(trip_purps, my_project):
    ''' Balances productions and attractions by purpose for all internal zones '''
    for purpose in trip_purps:
        print "Balancing trips for purpose: " + str(purpose)
        my_project.matrix_balancing(results_od_balanced_values = 'mf' + purpose + 'dis', 
                                    od_values_to_balance = 'mf' + purpose + 'fri', 
                                    origin_totals = 'mo' + purpose + 'pro', 
                                    destination_totals = 'md' + purpose + 'att', 
                                    constraint_by_zone_destinations = '1-' + str(HIGH_STATION), 
                                    constraint_by_zone_origins = '1-' + str(HIGH_STATION))

def calculate_daily_trips(trip_purps, my_project):
    # Accounting for out- and in-bound trips.
    # The distribution matrices (e.g. 'mfcoldis') are in PA format. Need to convert to OD format by transposing
    for purpose in trip_purps:
        my_project.matrix_calculator(result = 'mf' + purpose + 'od', 
                                     expression = '0.5*mf' + purpose + 'dis + 0.5*mf' + purpose + 'dis'+ "'")

def export_trips(split_by_mode_tod, output_dir):
    ''' Export combined trips to H5 '''

    for tod in time_periods:
        print "Exporting supplemental trips for time period: " + str(tod)
        my_store = h5py.File(output_dir + '/' + str(tod) + '.h5', "w-")
        for mode in mode_dict.keys(): 
            my_store.create_dataset(str(mode), data=split_by_mode_tod[mode][tod])
        my_store.close()

def trips_by_mode(trip_dict, trip_purps, my_project):
    ''' Distribute total daily O-D trips across Soundcast modes.  '''
    trips_by_mode = {}
    init_results = {}
    
    for mode, mode_values in mode_dict.iteritems():
        print "Splitting trips by mode for trip purpose: " + str(mode)
        for purpose in trip_purps:
            if purpose in ['hw1', 'hw2', 'hw3', 'hw4']:
                init_results[purpose] = mode_dict[mode]['hbw'] * trip_dict[purpose]
            else:
                init_results[purpose] = mode_dict[mode][purpose] * trip_dict[purpose]
        trips_by_mode[mode] = np.sum([init_results[purpose] for purpose in trip_purps],axis=0)

        # Divide HOV trips by average occupancy rates
        if mode == 'h2tl':
            trips_by_mode[mode] = trips_by_mode[mode]/2
        elif mode == 'h3tl':
            trips_by_mode[mode] = trips_by_mode[mode]/3.5

    return trips_by_mode

def trips_by_tod(trips_by_mode, trip_purps):
    ''' Distribute modal trips across times of day '''
    tod_df = {}
    trips_by_tod = {}
    for mode, tod_shares in time_dict.iteritems():
        for tod in time_periods:
            tod_df[tod] = trips_by_mode[mode] * time_dict[mode][tod]
            print tod
        trips_by_tod[mode] = tod_df
        tod_df = {}
        print mode
    return trips_by_tod

def distribute_trips(trip_table_in, results_dir, trip_purps, fric_facs, my_project):
    ''' Load data in Emme, balance trips by purpose, and produce O-D trip tables '''

    # Clear all existing matrices
    delete_matrices(my_project, "ORIGIN")
    delete_matrices(my_project, "DESTINATION")
    delete_matrices(my_project, "FULL")

    # Load data into fresh Emme matrices
    load_matrices_to_emme(trip_table_in, trip_purps, fric_facs, my_project)

    # Balance matrices
    balance_matrices(trip_purps, my_project)

    # Calculate daily trips
    calculate_daily_trips(trip_purps, my_project)


def split_trips(trip_dict, trip_purps, my_project):
    ''' Distribute trips by Soundcast user classes and TOD, using 2006 Survey shares '''
    by_mode = trips_by_mode(trip_dict, trip_purps, my_project)  # Distribute by mode
    by_tod = trips_by_tod(by_mode, trip_purps)  # Distribute by time of day

    return by_tod

def sum_by_purp(trip_purps, my_project):
    ''' For error checking, sum trips by trip purpose '''
    total_sum_by_purp = {}
    for purpose in trip_purps:
        print purpose
        # Load Emme O-D total trip data by purpose
        matrix_id = my_project.bank.matrix(purpose + 'od').id    
        emme_matrix = my_project.bank.matrix(matrix_id)  
        emme_data = emme_matrix.get_data() # Access emme data as numpy matrix
        emme_data = np.array(emme_data.raw_data, dtype='float64')
        total_sum_by_purp[purpose] = emme_data
    return total_sum_by_purp

def summarize_all_by_purp(ext_spg_summary, gq_summary, trip_purps):
    ''' For error checking, sum external, special generator, and group quarters tirps by purpose '''
    total_sum_by_purp = {}
    for purpose in trip_purps:   
    # Select only externals and special generators
        filtered = np.zeros_like(ext_spg_summary[purpose])
        # Add only special generator rows
        for loc_name, loc_zone in SPECIAL_GENERATORS.iteritems():
            # Add rows (minus 1 for zero-based NumPy index)
            filtered[[loc_zone - 1],:] = ext_spg_summary[purpose][[loc_zone - 1],:]
            # Add columns (minus 1 for zero-based NumPy index)
            filtered[:,[loc_zone]] = ext_spg_summary[purpose][:,[loc_zone]]
            # Combine with group quarters array
            if purpose not in ['hw2', 'hw3', 'hw4']:
                filtered += gq_summary[purpose]
        # Add only external rows and columns
        filtered[3700:,:] = ext_spg_summary[purpose][3700:,:]
        filtered[:,3700:] = ext_spg_summary[purpose][:,3700:]
        total_sum_by_purp[purpose] = filtered
    return total_sum_by_purp

def write_csv(data, file_name):
    with open(supplemental_loc + 'supplemental_summary.csv', 'wb') as f:
        csv_writer = csv.writer(f)
        csv_writer.writerows(data)

def ext_spg_selected(trip_purps):
    ''' Select only external and special generator zones '''
    total_sum_by_purp = {}
    for purpose in trip_purps:
        print purpose
        # Load Emme O-D total trip data by purpose
        matrix_id = my_project.bank.matrix(purpose + 'od').id    
        emme_matrix = my_project.bank.matrix(matrix_id)  
        emme_data = emme_matrix.get_data() # Access emme data as numpy matrix
        emme_data = np.array(emme_data.raw_data, dtype='float64')
        filtered = np.zeros_like(emme_data)
        # Add only special generator rows
        for loc_name, loc_zone in SPECIAL_GENERATORS.iteritems():
            # Add rows (minus 1 for zero-based NumPy index)
            filtered[[loc_zone - 1],:] = emme_data[[loc_zone - 1],:]
            # Add columns (minus 1 for zero-based NumPy index)
            filtered[:,[loc_zone]] = emme_data[:,[loc_zone]]
        # Add only external rows and columns
        filtered[3700:,:] = emme_data[3700:,:]
        filtered[:,3700:] = emme_data[:,3700:]

        total_sum_by_purp[purpose] = filtered
    return total_sum_by_purp

def supplementals_report(ext_spg_trimmed, gq_summary, combined, split_by_mode_tod):

    # Create an array to hold summary trips by purpose 
    sum_p = []
    sum_p.append([purp for purp in ext_spg_trimmed.keys()])
    sum_p[len(sum_p)-1].insert(0,"")
    sum_p.append([ext_spg_trimmed[purp].sum() for purp in ext_spg_trimmed.keys()])
    sum_p[len(sum_p)-1].insert(0,'Externals, Special Generators')
    sum_p.append([gq_summary[purp].sum() for purp in gq_summary.keys()])
    sum_p[len(sum_p)-1].insert(0,'Group Quarters')
    sum_p.append([combined[purp].sum() for purp in combined.keys()])
    sum_p[len(sum_p)-1].insert(0,'Totals')

    # Create array to hold summary trips by tod and mode
    sum_tm = []
    sum_tm.append([mode for mode in split_by_mode_tod.keys()])
    sum_tm[len(sum_tm)-1].insert(0,"")
    for tod in split_by_mode_tod['svtl'].keys():
        sum_tm.append([split_by_mode_tod[mode][tod].sum() for mode in split_by_mode_tod.keys()])
        sum_tm[len(sum_tm)-1].insert(0, tod)    # Insert TOD row heading

    write_csv(sum_p + [[]] + sum_tm, file_name='supplemental_summary.csv')

def main():

    # Overwrite previous trip tables 
    init_dir(supplemental_loc)

    # Load skim data
    am_cost_skim = load_skims(am_skim_file_loc, mode_name='svtl2g')
    am_dist_skim = load_skims(am_skim_file_loc, mode_name='svtl1d', divide_by_100=True)
    pm_cost_skim = load_skims(pm_skim_file_loc, mode_name='svtl2g')
    pm_dist_skim = load_skims(pm_skim_file_loc, mode_name='svtl1d', divide_by_100=True)
    cost_skim = (am_cost_skim + pm_cost_skim) * .5
    dist_skim = (am_cost_skim + pm_dist_skim) * .5
    # Import a network
    network_importer(my_project)

    # Compute friction factors by trip purpose
    fric_facs = calc_fric_fac(cost_skim, dist_skim)

    # Create trip table for externals and special generators by purpose and summarize
    distribute_trips(trip_table, ext_spg_dir, trip_purp_full, fric_facs, my_project)
    ext_spg_trimmed = ext_spg_selected(trip_purp_full)    # Include only external and special gen. zones

    # Distribute group quarters trips by purpose and summarize results
    distribute_trips(gq_trip_table, gq_directory, trip_purp_gq, fric_facs, my_project)
    gq_summary = sum_by_purp(trip_purp_gq, my_project)

    # Combine external, special gen., and group quarters trips
    combined = {}
    for purp in trip_purp_full:
        if purp not in ['hw2', 'hw3', 'hw4']:   # These purposes don't exist for GQ trips, use only for ext_spg
            combined[purp] = ext_spg_trimmed[purp] + gq_summary[purp]
        else:
            combined[purp] = ext_spg_trimmed[purp]

     # Split by mode and TOD
    split_by_mode_tod = split_trips(combined, trip_purp_full, my_project)

    # Export results to H5
    export_trips(split_by_mode_tod, output_dir = 'outputs/supplemental')

    # Report results in CSV summary
    supplementals_report(ext_spg_trimmed, gq_summary, combined, split_by_mode_tod)

my_project = EmmeProject(supplemental_project)
    
if __name__ == "__main__":
    main()